from __future__ import annotations

import json
import logging
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from icalendar import Calendar, Event

from src.api.models import (
    AddressItem,
    AddressLookupResponse,
    CollectionItem,
    CouncilInfo,
    HealthEntry,
    LookupResponse,
)
from src.api.rate_limiting import rate_limit
from waste_collection_schedule.exceptions import (
    SourceArgumentException,
    SourceArgumentExceptionMultiple,
)

logger = logging.getLogger(__name__)

_LOOKUP_PATH = (
    Path(__file__).parent.parent / "address_lookup" / "admin_scraper_lookup.json"
)
_DOMAIN_TO_SCRAPER: dict[str, str] = json.loads(_LOOKUP_PATH.read_text())


def _homepage_to_scraper_id(homepage_url: str) -> str | None:
    """Resolve a council homepage URL to a scraper ID via the domain lookup."""
    if not homepage_url.startswith(("http://", "https://")):
        homepage_url = "https://" + homepage_url
    domain = urlparse(homepage_url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return _DOMAIN_TO_SCRAPER.get(domain)


router = APIRouter()


@router.get("/addresses/{postcode}", response_model=AddressLookupResponse)
async def addresses(
    request: Request,
    postcode: str,
    _rate_limit: None = Depends(rate_limit),
):
    lookup = request.app.state.address_lookup
    try:
        addrs = await lookup.search_addresses(postcode)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Address lookup failed: {e}")

    try:
        authority = await lookup.get_local_authority(postcode)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Authority lookup failed: {e}")

    # If authority resolved to a single council, map homepage to scraper ID
    council_id = None
    council_name = None
    if hasattr(authority, "homepage_url"):
        council_name = authority.name
        council_id = _homepage_to_scraper_id(authority.homepage_url)

    return AddressLookupResponse(
        postcode=postcode.strip().upper(),
        council_id=council_id,
        council_name=council_name,
        addresses=[
            AddressItem(uprn=a.uprn, full_address=a.full_address, postcode=a.postcode)
            for a in addrs
        ],
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
            status_code=404, detail=f"Council scraper '{council}' not found"
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
        raise HTTPException(status_code=422, detail=str(e))
    except (httpx.HTTPError, TimeoutError) as e:
        registry.record_failure(council, str(e))
        raise HTTPException(status_code=503, detail=f"Council site unreachable: {e}")
    except Exception as e:
        registry.record_failure(council, str(e))
        logger.exception("Scraper %s failed", council)
        raise HTTPException(
            status_code=503, detail=f"Scraper error: {type(e).__name__}"
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
            status_code=404, detail=f"Council scraper '{council}' not found"
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
        raise HTTPException(status_code=422, detail=str(e))
    except (httpx.HTTPError, TimeoutError) as e:
        registry.record_failure(council, str(e))
        raise HTTPException(status_code=503, detail=f"Council site unreachable: {e}")
    except Exception as e:
        registry.record_failure(council, str(e))
        logger.exception("Scraper %s failed", council)
        raise HTTPException(
            status_code=503, detail=f"Scraper error: {type(e).__name__}"
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
