from __future__ import annotations

import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

from api import config
from api.services import address_lookup
from api.services import deeplinks as deeplink_service
from api.services.models import (
    AddressLookupResponse,
    AddressResult,
    CollectionItem,
    CouncilLookupResponse,
    DeeplinkInfo,
    LookupResponse,
)
from api.services.rate_limiting import _get_client_ip, rate_limit
from api.services.scrape_orchestrator import (
    DeeplinkAnswer,
    ScrapeHTTPException,
    build_scrape_params,
    get_or_scrape,
    is_cacheable_uprn,
    live_scrape,
    needs_browser_deeplink,
    resolve_council,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_UPRN_RE = re.compile(r"^[0-9]{1,20}$")

# On a /lookup answered with the fallback deeplink because the council's site
# failed: "network", "timeout" or "error" (see ScrapeHTTPException.failure).
# The body is the frontend's deeplink shape; this keeps the failure visible to
# the live test and to logs.
SCRAPE_FAILURE_HEADER = "X-Scrape-Failure"

COUNCIL_PARAM = Query(
    description="The council's ONS LAD code (e.g. E06000001), as /council/{postcode} returns it. "
    "Scraper IDs from before the switch to LAD codes still resolve.",
)


def _safe_uprn_filename(uprn: str) -> str:
    return uprn if _UPRN_RE.match(uprn) else "unknown"


def _deeplink_info(target: deeplink_service.Deeplink) -> DeeplinkInfo:
    return DeeplinkInfo(url=target.url, reason=target.reason, council_name=target.council_name)


async def verify_turnstile(request: Request) -> None:
    if not config.TURNSTILE_SECRET:
        return
    token = request.headers.get("X-Turnstile-Token")
    if not token:
        raise HTTPException(status_code=403, detail="Missing challenge token.")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": config.TURNSTILE_SECRET,
                    "response": token,
                    "remoteip": _get_client_ip(request),
                },
            )
        data = resp.json()
    except Exception:
        logger.exception("Turnstile verification request failed")
        raise HTTPException(status_code=503, detail="Challenge verification unavailable.")
    if not data.get("success"):
        logger.info("Turnstile verification failed: %s", data.get("error-codes"))
        raise HTTPException(status_code=403, detail="Challenge failed.")


@router.get("/addresses/{postcode}", response_model=AddressLookupResponse, include_in_schema=False)
async def addresses(
    request: Request,
    postcode: str,
    _rate_limit: None = Depends(rate_limit),
    _turnstile: None = Depends(verify_turnstile),
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
    council_id, council_name, candidates, lad_code = await resolve_council(
        request, lookup, postcode
    )

    deeplink = None
    if lad_code and not council_id:
        target = deeplink_service.resolve(lad_code)
        if target:
            deeplink = _deeplink_info(target)
    elif council_id:
        # A wired council whose scraper can never run without a browser
        # (captcha, login) answers like an unwired one: no address step.
        meta = request.app.state.registry.get(council_id)
        if meta is not None and meta.needs_browser:
            target = deeplink_service.for_needs_browser(meta, meta.needs_browser)
            if target:
                council_id, deeplink = None, _deeplink_info(target)

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
    registry = request.app.state.registry
    meta = registry.get(council)
    if meta is None:
        target = deeplink_service.resolve_by_council_param(council)
        if target:
            return LookupResponse(
                uprn=uprn,
                council=council,
                collections=[],
                deeplink=_deeplink_info(target),
            )
        raise HTTPException(
            status_code=404,
            detail="We don't have a scraper for this council yet. "
            "Check /api/v1/councils for the list of supported councils.",
        )

    try:
        if meta.needs_browser:
            raise needs_browser_deeplink(meta, meta.needs_browser)

        # `council` may be an old ID; answer, cache and log under the public one (the LAD code)
        params = build_scrape_params(meta, council, uprn, request.query_params)

        if meta.passthrough_url or not is_cacheable_uprn(uprn):
            collections = await live_scrape(request, meta.id, params)
            return LookupResponse(
                uprn=uprn,
                council=meta.id,
                cached=False,
                cached_at=None,
                collections=[
                    CollectionItem(date=c.date, type=c.type, icon=c.icon)
                    for c in collections
                ],
            )

        entry, cached = await get_or_scrape(request, uprn, meta.id, params)
    except DeeplinkAnswer as answer:
        return LookupResponse(
            uprn=uprn, council=meta.id, collections=[], deeplink=_deeplink_info(answer.deeplink)
        )
    except ScrapeHTTPException as error:
        # The council's site failed and nothing was cached (a cache hit never
        # scrapes): send the user to the council's page, as for an unwired council.
        if error.fallback is None:
            raise
        response.headers[SCRAPE_FAILURE_HEADER] = error.failure or "error"
        return LookupResponse(
            uprn=uprn, council=meta.id, collections=[], deeplink=_deeplink_info(error.fallback)
        )
    return LookupResponse(
        uprn=uprn,
        council=meta.id,
        cached=cached,
        cached_at=entry.last_success if cached else None,
        collections=[CollectionItem(**c) for c in entry.collections],
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
    registry = request.app.state.registry
    meta = registry.get(council)
    if meta is None:
        target = deeplink_service.resolve_by_council_param(council)
        if target:
            return RedirectResponse(url=target.url, status_code=302)
        raise HTTPException(
            status_code=404,
            detail="We don't have a scraper for this council yet. "
            "Check /api/v1/councils for the list of supported councils.",
        )

    try:
        if meta.needs_browser:
            raise needs_browser_deeplink(meta, meta.needs_browser)

        params = build_scrape_params(meta, council, uprn, request.query_params)

        if meta.passthrough_url:
            return RedirectResponse(url=meta.passthrough_url, status_code=302)

        if not is_cacheable_uprn(uprn):
            raise HTTPException(
                status_code=422,
                detail="A calendar subscription needs a real UPRN for your address.",
            )

        await get_or_scrape(request, uprn, meta.id, params)
    except DeeplinkAnswer as answer:
        # A calendar app can't follow a redirect to a web page; say it plainly.
        raise HTTPException(
            status_code=404,
            detail=f"We can't fetch bin days for this council: {answer.deeplink.reason}",
        ) from None

    cache = request.app.state.ics_cache
    ics_bytes = await cache.read_ics_bytes(uprn)
    if ics_bytes is None:
        raise HTTPException(
            status_code=503,
            detail="Calendar temporarily unavailable. Please try again later.",
        )
    safe_name = _safe_uprn_filename(uprn)
    return Response(
        content=ics_bytes,
        media_type="text/calendar",
        headers={
            "Content-Disposition": f'attachment; filename="bins-{safe_name}.ics"'
        },
    )
