from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from api import config
from api.config import SCRAPER_TIMEOUT
from api.services.models import CouncilInfo, SystemHealth

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


@router.get("/status", response_model=SystemHealth)
async def system_status(request: Request):
    registry = request.app.state.registry
    lookup = request.app.state.council_lookup
    all_ok = lookup.postcodes_loaded and lookup.lad_loaded
    if all_ok:
        status = "healthy"
    elif lookup.postcodes_loaded or lookup.lad_loaded:
        status = "degraded"
    else:
        status = "unhealthy"

    return SystemHealth(
        status=status,
        scraper_count=len(registry.list_all()),
        postcode_lookup=lookup.postcodes_loaded,
        lad_lookup=lookup.lad_loaded,
    )


@router.get("/metrics")
async def metrics(request: Request):
    registry = request.app.state.registry

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
        "scraper_count": len(registry.list_all()),
        "ics_cache": ics_info,
        "config": {
            "scraper_timeout": SCRAPER_TIMEOUT,
            "ics_retention_days": config.ICS_RETENTION_DAYS,
        },
    }
