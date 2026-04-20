from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from api.compat.hacs.exceptions import (
    SourceArgumentException,
    SourceArgumentExceptionMultiple,
)
from api.config import CACHE_TTL, RATE_LIMIT_DAILY, SCRAPER_TIMEOUT
from api.services import address_lookup
from api.services.council_lookup import LookupDatabaseError, PostcodeNotFoundError
from api.services.models import (
    AddressLookupResponse,
    AddressResult,
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


async def _acquire_scrape_lock(redis_client, uprn: str) -> bool:
    if redis_client is None:
        return True
    try:
        return bool(
            await redis_client.set(f"scrape-lock:{uprn}", "1", nx=True, ex=30)
        )
    except Exception:
        logger.warning("Scrape lock acquire failed", exc_info=True)
        return True


async def _release_scrape_lock(redis_client, uprn: str) -> None:
    if redis_client is None:
        return
    try:
        await redis_client.delete(f"scrape-lock:{uprn}")
    except Exception:
        pass


def _map_scrape_exception(council: str, exc: Exception) -> HTTPException:
    if isinstance(exc, (SourceArgumentException, SourceArgumentExceptionMultiple)):
        return HTTPException(
            status_code=422,
            detail="The details provided don't match what this council's system expects. "
            "Please check your UPRN and postcode are correct.",
        )
    if isinstance(exc, ScraperTimeoutError):
        return HTTPException(
            status_code=504,
            detail="Your council's website is taking too long to respond. "
            "Please try again later.",
        )
    if isinstance(exc, (httpx.HTTPError, TimeoutError)):
        return HTTPException(
            status_code=503,
            detail="We couldn't reach your council's website. "
            "The site may be temporarily down \u2014 please try again later.",
        )
    logger.exception("Scraper %s failed", council)
    return HTTPException(
        status_code=503,
        detail="Something went wrong while fetching your collection schedule. "
        "Please try again later.",
    )


def _build_scrape_params(
    meta, council: str, uprn: str, query_params
) -> dict[str, str]:
    params: dict[str, str] = {}
    if uprn and uprn != "0":
        params["uprn"] = uprn
    for key, value in query_params.items():
        if key != "council" and value:
            params[key] = value
    missing = [p for p in meta.required_params if p not in params]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required parameters for {council}: {missing}. "
            f"Required: {meta.required_params}, Optional: {meta.optional_params}",
        )
    return params


async def _get_or_scrape(request, uprn: str, council: str, params: dict[str, str]):
    """Return (CacheEntry, cached) — handles cache, lock, scrape, write."""
    cache = request.app.state.ics_cache
    registry = request.app.state.registry
    redis_client = getattr(request.app.state, "redis", None)

    entry = await cache.read(uprn)
    if entry is not None and entry.last_success is not None:
        return entry, True

    lock_acquired = await _acquire_scrape_lock(redis_client, uprn)
    try:
        if not lock_acquired:
            await asyncio.sleep(0.5)
            entry = await cache.read(uprn)
            if entry is not None and entry.last_success is not None:
                return entry, True

        try:
            collections = await registry.invoke(council, params)
            registry.record_success(council)
        except Exception as exc:
            registry.record_failure(council, str(exc))
            await cache.record_failure(uprn, str(exc))
            raise _map_scrape_exception(council, exc) from exc

        entry = await cache.write(uprn, council, params, collections)
        return entry, False
    finally:
        if lock_acquired:
            await _release_scrape_lock(redis_client, uprn)

async def _resolve_council(
    request: Request, lookup, postcode: str
) -> tuple[str, str]:
    """Resolve postcode to a single council, raising HTTPException otherwise."""
    request_id = getattr(request.state, "request_id", None)
    log_extra = {"request_id": request_id, "postcode": postcode}
    try:
        authorities = await lookup.get_local_authority(postcode)
    except LookupDatabaseError:
        logger.warning("Postcode lookup DB unavailable", extra=log_extra)
        raise HTTPException(
            status_code=503,
            detail="Our postcode lookup service is temporarily unavailable. "
            "Please try again later.",
        )
    except PostcodeNotFoundError:
        logger.info("Postcode not found", extra=log_extra)
        raise HTTPException(
            status_code=404,
            detail="We couldn't find that postcode in our database. "
            "Please check it's correct. If it's a new postcode, "
            "our data may not include it yet.",
        )

    if len(authorities) == 1:
        authority = authorities[0]
        if not authority.slug:
            logger.info(
                "Postcode resolved to unsupported council %s",
                authority.name,
                extra=log_extra,
            )
            raise HTTPException(
                status_code=404,
                detail=f"We found your council ({authority.name}) but don't have "
                "a scraper for it yet. Check /api/v1/councils for supported councils.",
            )
        return authority.slug, authority.name

    logger.info(
        "Ambiguous postcode: %d candidate councils",
        len(authorities),
        extra=log_extra,
    )
    candidates = [
        {"slug": a.slug, "name": a.name, "homepage_url": a.homepage_url}
        for a in authorities
        if a.slug
    ]
    raise HTTPException(
        status_code=300,
        detail={
            "message": "This postcode straddles multiple councils. "
            "Please pick the one that covers your address.",
            "candidates": candidates,
        },
    )


@router.get("/addresses/{postcode}", response_model=AddressLookupResponse)
async def addresses(
    postcode: str,
    _rate_limit: None = Depends(rate_limit),
):
    try:
        results = await address_lookup.search_addresses(postcode)
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="The address lookup service is taking too long to respond. "
            "Please try again later.",
        )
    except httpx.HTTPStatusError as e:
        logger.warning("Address lookup HTTP error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="The address lookup service is temporarily unavailable. "
            "Please try again later.",
        )
    except Exception:
        logger.exception("Address lookup failed")
        raise HTTPException(
            status_code=503,
            detail="Something went wrong during the address lookup. "
            "Please try again later.",
        )

    return AddressLookupResponse(
        postcode=postcode.strip().upper(),
        addresses=[AddressResult(**r) for r in results],
    )


@router.get("/council/{postcode}", response_model=CouncilLookupResponse)
async def council_lookup(
    request: Request,
    postcode: str,
    _rate_limit: None = Depends(rate_limit),
):
    lookup = request.app.state.council_lookup
    council_id, council_name = await _resolve_council(request, lookup, postcode)

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

    params = _build_scrape_params(meta, council, uprn, request.query_params)
    entry, cached = await _get_or_scrape(request, uprn, council, params)

    return LookupResponse(
        uprn=uprn,
        council=council,
        cached=cached,
        cached_at=entry.last_success if cached else None,
        collections=[CollectionItem(**c) for c in entry.collections],
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

    params = _build_scrape_params(meta, council, uprn, request.query_params)
    await _get_or_scrape(request, uprn, council, params)

    cache = request.app.state.ics_cache
    ics_bytes = await cache.read_ics_bytes(uprn)
    if ics_bytes is None:
        raise HTTPException(
            status_code=503,
            detail="Calendar temporarily unavailable. Please try again later.",
        )
    return Response(
        content=ics_bytes,
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

    ics_cache = getattr(request.app.state, "ics_cache", None)
    refresh_job = getattr(request.app.state, "refresh_job", None)
    ics_info = None
    if ics_cache is not None:
        ics_info = {
            "entries": sum(1 for _ in ics_cache.iter_entries()),
            "last_refresh": refresh_job.last_run.isoformat()
            if refresh_job and refresh_job.last_run
            else None,
            "last_refresh_stats": (
                refresh_job.last_stats.__dict__
                if refresh_job and refresh_job.last_stats
                else None
            ),
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
        "ics_cache": ics_info,
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
