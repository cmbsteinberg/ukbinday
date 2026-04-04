from __future__ import annotations

import logging
import uuid
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from icalendar import Calendar, Event

from api.compat.hacs.exceptions import (
    SourceArgumentException,
    SourceArgumentExceptionMultiple,
)
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
    params: dict[str, str] = {"uprn": uprn}
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

    return LookupResponse(
        uprn=uprn,
        council=council,
        collections=[
            CollectionItem(
                date=c.date,
                type=c.type,
                icon=c.icon,
            )
            for c in collections
        ],
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

    params: dict[str, str] = {"uprn": uprn}
    for key, value in request.query_params.items():
        if key != "council" and value:
            params[key] = value

    missing = [p for p in meta.required_params if p not in params]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required parameters for {council}: {missing}",
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

    cal = Calendar()
    cal.add("prodid", "-//UK Bin Collections//bins//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"Bin Collections ({uprn})")

    for c in collections:
        event = Event()
        event.add("summary", c.type)
        event.add("dtstart", c.date)
        event.add("dtend", c.date + timedelta(days=1))
        event.add("uid", str(uuid.uuid4()))
        if c.icon:
            event.add("description", c.icon)
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
