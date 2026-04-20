from __future__ import annotations

import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from api import config
from api.services import address_lookup
from api.services.models import (
    AddressLookupResponse,
    AddressResult,
    CollectionItem,
    CouncilLookupResponse,
    LookupResponse,
)
from api.services.rate_limiting import _get_client_ip, rate_limit
from api.services.scrape_orchestrator import (
    build_scrape_params,
    get_or_scrape,
    live_scrape,
    resolve_council,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_UPRN_RE = re.compile(r"^[0-9]{1,20}$")


def _safe_uprn_filename(uprn: str) -> str:
    return uprn if _UPRN_RE.match(uprn) else "unknown"


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
    council_id, council_name, candidates = await resolve_council(
        request, lookup, postcode
    )

    return CouncilLookupResponse(
        postcode=postcode.strip().upper(),
        council_id=council_id,
        council_name=council_name,
        candidates=candidates,
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

    params = build_scrape_params(meta, council, uprn, request.query_params)

    if meta.passthrough_url:
        collections = await live_scrape(request, council, params)
        return LookupResponse(
            uprn=uprn,
            council=council,
            cached=False,
            cached_at=None,
            collections=[
                CollectionItem(date=c.date, type=c.type, icon=c.icon)
                for c in collections
            ],
        )

    entry, cached = await get_or_scrape(request, uprn, council, params)
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

    params = build_scrape_params(meta, council, uprn, request.query_params)

    if meta.passthrough_url:
        return RedirectResponse(url=meta.passthrough_url, status_code=302)

    await get_or_scrape(request, uprn, council, params)

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
