from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from api.routes.schedule import (
    SCRAPE_FAILURE_HEADER,
    calendar_response,
    deeplink_info,
    get_schedule,
    search_addresses,
    verify_turnstile,
)
from api.services import deeplinks as deeplink_service
from api.services.models import (
    AddressLookupResponse,
    CouncilLookupResponse,
    LookupResponse,
)
from api.services.rate_limiting import rate_limit
from api.services.scrape_orchestrator import resolve_council

logger = logging.getLogger(__name__)

router = APIRouter()

COUNCIL_PARAM = Query(
    description="The council's ONS LAD code (e.g. E06000001), as /council/{postcode} returns it. "
    "Scraper IDs from before the switch to LAD codes still resolve.",
)


@router.get("/addresses/{postcode}", response_model=AddressLookupResponse, include_in_schema=False)
async def addresses(
    request: Request,
    postcode: str,
    _rate_limit: None = Depends(rate_limit),
    _turnstile: None = Depends(verify_turnstile),
):
    return await search_addresses(postcode)


@router.get("/council/{postcode}", response_model=CouncilLookupResponse)
async def council_lookup(
    request: Request,
    postcode: str,
    _rate_limit: None = Depends(rate_limit),
):
    lookup = request.app.state.council_lookup
    council_id, council_name, candidates, lad_code = await resolve_council(
        request, lookup, postcode
    )

    deeplink = None
    if lad_code and not council_id:
        target = deeplink_service.resolve(lad_code)
        if target:
            deeplink = deeplink_info(target)
    elif council_id:
        # A wired council whose scraper can never run without a browser
        # (captcha, login) answers like an unwired one: no address step.
        meta = request.app.state.registry.get(council_id)
        if meta is not None and meta.needs_browser:
            target = deeplink_service.for_needs_browser(meta, meta.needs_browser)
            if target:
                council_id, deeplink = None, deeplink_info(target)

    return CouncilLookupResponse(
        postcode=postcode.strip().upper(),
        council_id=council_id,
        council_name=council_name,
        candidates=candidates,
        deeplink=deeplink,
    )


@router.get("/lookup/{uprn}", response_model=LookupResponse)
async def lookup(
    request: Request,
    response: Response,
    uprn: str,
    council: str = COUNCIL_PARAM,
    postcode: str | None = None,
    address: str | None = None,
    _rate_limit: None = Depends(rate_limit),
):
    schedule = await get_schedule(request, uprn, council)
    if schedule.failure:
        response.headers[SCRAPE_FAILURE_HEADER] = schedule.failure
    return LookupResponse(
        uprn=uprn,
        council=schedule.council,
        cached=schedule.cached,
        cached_at=schedule.cached_at,
        collections=schedule.collections,
        deeplink=schedule.deeplink,
    )


@router.get("/calendar/{uprn}")
async def calendar(
    request: Request,
    uprn: str,
    council: str = COUNCIL_PARAM,
    postcode: str | None = None,
    address: str | None = None,
    _rate_limit: None = Depends(rate_limit),
):
    return await calendar_response(request, uprn, council, attachment=True)
