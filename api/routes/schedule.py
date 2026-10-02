"""The lookup, calendar and address logic both API versions answer with.

v1 (`lookup.py`) and v2 (`v2.py`) differ only in how they shape the answer;
everything that decides it (registry resolution, unwired and NeedsBrowser
deeplinks, cache-or-scrape, the upstream-failure fallback) lives here once.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from api import config
from api.services import address_lookup
from api.services import deeplinks as deeplink_service
from api.services.models import (
    AddressLookupResponse,
    AddressResult,
    CollectionItem,
    DeeplinkInfo,
)
from api.services.rate_limiting import _get_client_ip
from api.services.scrape_orchestrator import (
    DeeplinkAnswer,
    ScrapeHTTPException,
    build_scrape_params,
    get_or_scrape,
    is_cacheable_uprn,
    live_scrape,
    needs_browser_deeplink,
)

logger = logging.getLogger(__name__)

_UPRN_RE = re.compile(r"^[0-9]{1,20}$")

# On a lookup answered with the fallback deeplink because the council's site
# failed: "network", "timeout" or "error" (see ScrapeHTTPException.failure).
# The body is the frontend's deeplink shape; this keeps the failure visible to
# the live test and to logs.
SCRAPE_FAILURE_HEADER = "X-Scrape-Failure"


def _safe_uprn_filename(uprn: str) -> str:
    return uprn if _UPRN_RE.match(uprn) else "unknown"


def deeplink_info(target: deeplink_service.Deeplink) -> DeeplinkInfo:
    return DeeplinkInfo(url=target.url, reason=target.reason, council_name=target.council_name)


def _no_scraper() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail="We don't have a scraper for this council yet. "
        "Check /api/v1/councils for the list of supported councils.",
    )


@dataclass(frozen=True)
class Schedule:
    """A lookup's answer before either version shapes it.

    `council` is the public ID (the LAD code) for a wired council, else the
    council as the caller gave it. `failure` is the `X-Scrape-Failure` value
    when the answer is the upstream-failure deeplink.
    """

    council: str
    collections: list[CollectionItem]
    cached: bool = False
    cached_at: datetime | None = None
    deeplink: DeeplinkInfo | None = None
    failure: str | None = None


async def get_schedule(request: Request, uprn: str, council: str) -> Schedule:
    """Collections for a UPRN: cache or scrape, or the deeplink to send the user to.

    Raises the mapped HTTP error (404 unknown council, 422 bad input, 503/504
    when the site failed and there's no deeplink to fall back on).
    """
    meta = request.app.state.registry.get(council)
    if meta is None:
        target = deeplink_service.resolve_by_council_param(council)
        if target:
            return Schedule(council=council, collections=[], deeplink=deeplink_info(target))
        raise _no_scraper()

    try:
        if meta.needs_browser:
            raise needs_browser_deeplink(meta, meta.needs_browser)

        # `council` may be an old ID; answer, cache and log under the public one (the LAD code)
        params = build_scrape_params(meta, council, uprn, request.query_params)

        if not is_cacheable_uprn(uprn):
            collections = await live_scrape(request, meta.id, params)
            return Schedule(
                council=meta.id,
                collections=[CollectionItem(date=c.date, type=c.type, icon=c.icon) for c in collections],
            )

        entry, cached = await get_or_scrape(request, uprn, meta.id, params)
    except DeeplinkAnswer as answer:
        return Schedule(council=meta.id, collections=[], deeplink=deeplink_info(answer.deeplink))
    except ScrapeHTTPException as error:
        # The council's site failed and nothing was cached (a cache hit never
        # scrapes): send the user to the council's page, as for an unwired council.
        if error.fallback is None:
            raise
        return Schedule(
            council=meta.id,
            collections=[],
            deeplink=deeplink_info(error.fallback),
            failure=error.failure or "error",
        )
    return Schedule(
        council=meta.id,
        collections=[CollectionItem(**c) for c in entry.collections],
        cached=cached,
        cached_at=entry.last_success if cached else None,
    )


async def calendar_response(
    request: Request, uprn: str, council: str, *, attachment: bool
) -> Response:
    """The UPRN's ICS (scraping it first on a cache miss), or a redirect to the
    unwired council's page. `attachment` adds a download Content-Disposition."""
    meta = request.app.state.registry.get(council)
    if meta is None:
        target = deeplink_service.resolve_by_council_param(council)
        if target:
            return RedirectResponse(url=target.url, status_code=302)
        raise _no_scraper()

    try:
        if meta.needs_browser:
            raise needs_browser_deeplink(meta, meta.needs_browser)

        params = build_scrape_params(meta, council, uprn, request.query_params)

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
    headers = {}
    if attachment:
        headers["Content-Disposition"] = f'attachment; filename="bins-{_safe_uprn_filename(uprn)}.ics"'
    return Response(content=ics_bytes, media_type="text/calendar", headers=headers)


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


async def search_addresses(postcode: str) -> AddressLookupResponse:
    """Addresses for a postcode from the address API, with its failures as HTTP errors."""
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
