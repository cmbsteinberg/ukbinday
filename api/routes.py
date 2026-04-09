from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from icalendar import Calendar, Event
from pydantic import BaseModel

from api.compat.hacs.exceptions import (
    SourceArgumentException,
    SourceArgumentExceptionMultiple,
)
from api.config import CACHE_TTL, RATE_LIMIT_DAILY, SCRAPER_TIMEOUT
from api.services.council_lookup import LookupDatabaseError, PostcodeNotFoundError
from api.services.models import (
    CollectionItem,
    CouncilInfo,
    CouncilLookupResponse,
    HealthEntry,
    LookupResponse,
    SystemHealth,
)
from api.services.rate_limiting import rate_limit
from api.services.scraper_registry import ScraperTimeoutError

logger = logging.getLogger(__name__)

router = APIRouter()


def _cache_key(council: str, params: dict) -> str:
    """Build a deterministic Redis key from council + sorted params."""
    parts = ":".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"cache:{council}:{parts}"


async def _cache_get(redis_client, key: str) -> dict | None:
    """Try to read cached scraper result from Redis."""
    if not redis_client:
        return None
    try:
        raw = await redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        logger.warning("Redis cache read failed for key %s", key, exc_info=True)
    return None


async def _cache_set(redis_client, key: str, collections: list[dict]) -> None:
    """Write scraper result to Redis with TTL."""
    if not redis_client:
        return
    try:
        payload = json.dumps(
            {"collections": collections, "cached_at": datetime.now().isoformat()}
        )
        await redis_client.set(key, payload, ex=CACHE_TTL)
    except Exception:
        logger.warning("Redis cache write failed for key %s", key, exc_info=True)


async def _resolve_council(lookup, postcode: str) -> tuple[str | None, str | None]:
    """Resolve postcode to council, raising HTTPException on distinct failures."""
    try:
        authorities = await lookup.get_local_authority(postcode)
    except LookupDatabaseError:
        raise HTTPException(
            status_code=503,
            detail="Our postcode lookup service is temporarily unavailable. "
            "Please try again later.",
        )
    except PostcodeNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="We couldn't find that postcode in our database. "
            "Please check it's correct. If it's a new postcode, "
            "our data may not include it yet.",
        )

    if len(authorities) == 1:
        council_name = authorities[0].name
        council_id = authorities[0].slug or None
        if not council_id:
            raise HTTPException(
                status_code=404,
                detail=f"We found your council ({council_name}) but don't have "
                "a scraper for it yet. Check /api/v1/councils for supported councils.",
            )
        return council_id, council_name

    return None, None


@router.get("/council/{postcode}", response_model=CouncilLookupResponse)
async def council_lookup(
    request: Request,
    postcode: str,
    _rate_limit: None = Depends(rate_limit),
):
    lookup = request.app.state.council_lookup
    council_id, council_name = await _resolve_council(lookup, postcode)

    return CouncilLookupResponse(
        postcode=postcode.strip().upper(),
        council_id=council_id,
        council_name=council_name,
    )


@router.get("/lookup/{uprn}", response_model=LookupResponse)
async def lookup(
    request: Request,
    uprn: str,
    council: str,
    postcode: str | None = None,
    address: str | None = None,
    _rate_limit: None = Depends(rate_limit),
):
    registry = request.app.state.registry
    meta = registry.get(council)
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail="We don't have a scraper for this council yet. "
            "Check /api/v1/councils for the list of supported councils.",
        )

    # Build params from path + query, excluding 'council' which is routing-only
    params: dict[str, str] = {}
    if uprn and uprn != "0":
        params["uprn"] = uprn
    for key, value in request.query_params.items():
        if key != "council" and value:
            params[key] = value

    # Validate required params
    missing = [p for p in meta.required_params if p not in params]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required parameters for {council}: {missing}. "
            f"Required: {meta.required_params}, Optional: {meta.optional_params}",
        )

    # Check cache
    redis_client = getattr(request.app.state, "redis", None)
    key = _cache_key(council, params)
    cached = await _cache_get(redis_client, key)
    if cached:
        return LookupResponse(
            uprn=uprn,
            council=council,
            cached=True,
            cached_at=datetime.fromisoformat(cached["cached_at"]),
            collections=[CollectionItem(**c) for c in cached["collections"]],
        )

    try:
        collections = await registry.invoke(council, params)
        registry.record_success(council)
    except (SourceArgumentException, SourceArgumentExceptionMultiple) as e:
        registry.record_failure(council, str(e))
        raise HTTPException(
            status_code=422,
            detail="The details provided don't match what this council's system expects. "
            "Please check your UPRN and postcode are correct.",
        )
    except ScraperTimeoutError as e:
        registry.record_failure(council, str(e))
        raise HTTPException(
            status_code=504,
            detail="Your council's website is taking too long to respond. "
            "Please try again later.",
        )
    except (httpx.HTTPError, TimeoutError) as e:
        registry.record_failure(council, str(e))
        raise HTTPException(
            status_code=503,
            detail="We couldn't reach your council's website. "
            "The site may be temporarily down — please try again later.",
        )
    except Exception as e:
        registry.record_failure(council, str(e))
        logger.exception("Scraper %s failed", council)
        raise HTTPException(
            status_code=503,
            detail="Something went wrong while fetching your collection schedule. "
            "Please try again later.",
        )

    items = [CollectionItem(date=c.date, type=c.type, icon=c.icon) for c in collections]

    # Write to cache
    await _cache_set(redis_client, key, [i.model_dump(mode="json") for i in items])

    return LookupResponse(
        uprn=uprn,
        council=council,
        collections=items,
    )


@router.get("/calendar/{uprn}")
async def calendar(
    request: Request,
    uprn: str,
    council: str,
    postcode: str | None = None,
    address: str | None = None,
    _rate_limit: None = Depends(rate_limit),
):
    registry = request.app.state.registry
    meta = registry.get(council)
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail="We don't have a scraper for this council yet. "
            "Check /api/v1/councils for the list of supported councils.",
        )

    params: dict[str, str] = {}
    if uprn and uprn != "0":
        params["uprn"] = uprn
    for key, value in request.query_params.items():
        if key != "council" and value:
            params[key] = value

    missing = [p for p in meta.required_params if p not in params]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required parameters for {council}: {missing}",
        )

    # Check cache — reuse same cache as /lookup
    redis_client = getattr(request.app.state, "redis", None)
    key = _cache_key(council, params)
    cached = await _cache_get(redis_client, key)
    if cached:
        collections_data = cached["collections"]
    else:
        try:
            raw_collections = await registry.invoke(council, params)
            registry.record_success(council)
        except (SourceArgumentException, SourceArgumentExceptionMultiple) as e:
            registry.record_failure(council, str(e))
            raise HTTPException(
                status_code=422,
                detail="The details provided don't match what this council's system expects. "
                "Please check your UPRN and postcode are correct.",
            )
        except ScraperTimeoutError as e:
            registry.record_failure(council, str(e))
            raise HTTPException(
                status_code=504,
                detail="Your council's website is taking too long to respond. "
                "Please try again later.",
            )
        except (httpx.HTTPError, TimeoutError) as e:
            registry.record_failure(council, str(e))
            raise HTTPException(
                status_code=503,
                detail="We couldn't reach your council's website. "
                "The site may be temporarily down — please try again later.",
            )
        except Exception as e:
            registry.record_failure(council, str(e))
            logger.exception("Scraper %s failed", council)
            raise HTTPException(
                status_code=503,
                detail="Something went wrong while fetching your collection schedule. "
                "Please try again later.",
            )
        collections_data = [
            {"date": str(c.date), "type": c.type, "icon": c.icon}
            for c in raw_collections
        ]
        await _cache_set(redis_client, key, collections_data)

    cal = Calendar()
    cal.add("prodid", "-//UK Bin Collections//bins//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"Bin Collections ({uprn})")

    for c in collections_data:
        event = Event()
        event.add("summary", c["type"])
        event.add("dtstart", date.fromisoformat(c["date"]))
        event.add("dtend", date.fromisoformat(c["date"]) + timedelta(days=1))
        event.add("uid", str(uuid.uuid4()))
        if c.get("icon"):
            event.add("description", c["icon"])
        cal.add_component(event)

    return Response(
        content=cal.to_ical(),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="bins-{uprn}.ics"'},
    )


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
        "config": {
            "cache_ttl": CACHE_TTL,
            "scraper_timeout": SCRAPER_TIMEOUT,
            "rate_limit_daily": RATE_LIMIT_DAILY,
        },
    }


class ReportRequest(BaseModel):
    postcode: str
    address: str
    uprn: str
    council: str
    collections: list[dict]


report_logger = logging.getLogger("api.reports")


@router.post("/report")
async def report_wrong(body: ReportRequest):
    collections_text = ", ".join(
        f"{c.get('type', '?')} ({c.get('date', '?')})" for c in body.collections
    )
    report_logger.warning(
        "User report: postcode=%s council=%s uprn=%s address=%s collections=[%s]",
        body.postcode,
        body.council,
        body.uprn,
        body.address,
        collections_text,
    )
    return {"status": "logged"}
