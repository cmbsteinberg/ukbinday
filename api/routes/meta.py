from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from api import config
from api.config import RATE_LIMIT_HOURLY, SCRAPER_TIMEOUT
from api.services.models import CouncilInfo, HealthEntry, SystemHealth

logger = logging.getLogger(__name__)

router = APIRouter()


def _ics_info(heartbeat: dict | None) -> dict:
    """Cache figures from the refresh heartbeat: entries summed over the shards,
    and the age of the *oldest* shard's last run, which is what a monitor alerts on."""
    shards = (heartbeat or {}).get("shards", {})
    if not shards:
        return {
            "entries": None,
            "last_refresh": None,
            "last_refresh_age_seconds": None,
            "shards_expected": None,
            "last_refresh_stats": None,
        }
    oldest = min(datetime.fromisoformat(s["last_run"]) for s in shards.values())
    return {
        "entries": sum(s["entries"] for s in shards.values()),
        "last_refresh": oldest.isoformat(),
        "last_refresh_age_seconds": round((datetime.now(UTC) - oldest).total_seconds()),
        "shards_expected": heartbeat["of"],
        "last_refresh_stats": {i: s["stats"] for i, s in shards.items()},
    }


@router.get("/councils", response_model=list[CouncilInfo])
async def list_councils(request: Request):
    registry = request.app.state.registry
    return [
        CouncilInfo(
            id=m.id,
            name=m.title,
            url=m.url,
            params=m.required_params + m.optional_params,
        )
        for m in registry.list_all()
    ]


@router.get("/health", response_model=list[HealthEntry])
async def health(request: Request):
    registry = request.app.state.registry
    return [
        HealthEntry(
            id=m.id,
            name=m.title,
            status=registry.get_health(m.id).status,
            last_success=registry.get_health(m.id).last_success,
            last_error=registry.get_health(m.id).last_error,
            error_count=registry.get_health(m.id).error_count,
        )
        for m in registry.list_all()
    ]


@router.get("/status", response_model=SystemHealth)
async def system_status(request: Request):
    registry = request.app.state.registry
    lookup = request.app.state.council_lookup
    redis_client = getattr(request.app.state, "redis", None)

    redis_ok = False
    if redis_client is not None:
        try:
            await redis_client.ping()
            redis_ok = True
        except Exception:
            pass

    all_ok = lookup.parquet_loaded and lookup.lad_loaded
    if all_ok:
        status = "healthy"
    elif lookup.parquet_loaded or lookup.lad_loaded:
        status = "degraded"
    else:
        status = "unhealthy"

    return SystemHealth(
        status=status,
        scraper_count=len(registry.list_all()),
        postcode_lookup=lookup.parquet_loaded,
        lad_lookup=lookup.lad_loaded,
        redis_connected=redis_ok,
        rate_limiting_active=redis_ok,
    )


@router.get("/metrics")
async def metrics(request: Request):
    redis_client = getattr(request.app.state, "redis", None)
    request_counts: dict[str, int] = {}
    if redis_client:
        try:
            raw = await redis_client.hgetall("api:request_counts")
            request_counts = {
                k.decode() if isinstance(k, bytes) else k: int(v)
                for k, v in raw.items()
            }
        except Exception:
            logger.warning("Failed to read metrics from Redis", exc_info=True)

    registry = request.app.state.registry
    scraper_health = {}
    for m in registry.list_all():
        h = registry.get_health(m.id)
        scraper_health[m.id] = {
            "status": h.status,
            "error_count": h.error_count,
        }

    ics_cache = getattr(request.app.state, "ics_cache", None)
    ics_info = None
    if ics_cache is not None:
        try:
            heartbeat = await ics_cache.read_heartbeat()
        except Exception:
            logger.warning("Failed to read refresh heartbeat", exc_info=True)
            heartbeat = None
        ics_info = _ics_info(heartbeat)

    return {
        "request_counts": request_counts,
        "scraper_count": len(registry.list_all()),
        "scraper_health_summary": {
            "healthy": sum(
                1 for v in scraper_health.values() if v["status"] == "healthy"
            ),
            "unhealthy": sum(
                1 for v in scraper_health.values() if v["status"] != "healthy"
            ),
        },
        "ics_cache": ics_info,
        "config": {
            "scraper_timeout": SCRAPER_TIMEOUT,
            "rate_limit_hourly": RATE_LIMIT_HOURLY,
            "ics_retention_days": config.ICS_RETENTION_DAYS,
        },
    }
