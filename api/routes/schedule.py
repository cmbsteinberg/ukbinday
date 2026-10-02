"""What the API answers: a postcode's council and addresses, a UPRN's schedule
and its calendar. Registry resolution, unwired and NeedsBrowser deeplinks,
cache-or-scrape and the upstream-failure fallback live here; `v2.py` is the
routes over them.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import date

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from api import config
from api.councils._base import colour_of
from api.services import address_lookup
from api.services import deeplinks as deeplink_service
from api.services.bank_holidays import holiday_name
from api.services.blob_store import BlobStoreError
from api.services.models import (
    AddressResult,
    CollectionDate,
    CollectionType,
    DeeplinkInfo,
    FindResponse,
    ScheduleResponse,
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
    resolve_council,
)

logger = logging.getLogger(__name__)

_UPRN_RE = re.compile(r"^[0-9]{1,20}$")

# On a schedule answered with the fallback deeplink because the council's site
# failed: "network", "blocked", "timeout" or "error" (see ScrapeHTTPException.failure).
# The body is the frontend's deeplink shape; this keeps the failure visible to
# the live test and to logs.
SCRAPE_FAILURE_HEADER = "X-Scrape-Failure"


def _safe_uprn_filename(uprn: str) -> str:
    return uprn if _UPRN_RE.match(uprn) else "unknown"


def deeplink_info(target: deeplink_service.Deeplink) -> DeeplinkInfo:
    return DeeplinkInfo(
        url=target.url,
        reason=target.reason,
        council_name=target.council_name,
        blocker=target.blocker,
        blocker_label=target.blocker.label,
    )


def _no_scraper() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail="We don't have a scraper for this council yet. "
        "Check /api/v2/councils for the list of supported councils.",
    )


def _dates(lad: str, collections: Iterable[tuple[date | str, str, str | None]]) -> list[CollectionDate]:
    """(date, label, icon) rows as ascending dates, each with its bin colour and bank holiday."""
    rows = sorted(
        ((date.fromisoformat(d) if isinstance(d, str) else d, label, icon) for d, label, icon in collections),
        key=lambda row: row[:2],
    )
    return [
        CollectionDate(
            date=d,
            holiday=holiday_name(lad, d),
            type=CollectionType(label=label, colour=colour_of(label), icon=icon),
        )
        for d, label, icon in rows
    ]


async def get_schedule(
    request: Request, response: Response, uprn: str, council: str, *, fresh: bool = False
) -> ScheduleResponse:
    """Collection dates for a UPRN: cache or scrape, or the deeplink to send the user to.

    `council` may be an old scraper ID; the answer carries the public one (the
    LAD code) for a wired council. When the answer is the upstream-failure
    deeplink, `X-Scrape-Failure` goes on `response`. Raises the mapped HTTP
    error (404 unknown council, 422 bad input, 503/504 when the site failed
    and there's no deeplink to fall back on). `fresh` scrapes without reading
    or writing the cache, as for UPRN 0.
    """
    meta = request.app.state.registry.get(council)
    if meta is None:
        target = deeplink_service.resolve_by_council_param(council)
        if target:
            return ScheduleResponse(uprn=uprn, council=council, deeplink=deeplink_info(target))
        raise _no_scraper()

    try:
        if meta.needs_browser:
            raise needs_browser_deeplink(meta, meta.needs_browser)

        # answer, cache and log under the public ID (the LAD code)
        params = build_scrape_params(meta, council, uprn, request.query_params)

        if fresh or not is_cacheable_uprn(uprn):
            collections = await live_scrape(request, meta.id, params)
            return ScheduleResponse(
                uprn=uprn,
                council=meta.id,
                dates=_dates(meta.id, ((c.date, c.type, c.icon) for c in collections)),
            )

        entry, cached = await get_or_scrape(request, uprn, meta.id, params)
    except DeeplinkAnswer as answer:
        return ScheduleResponse(uprn=uprn, council=meta.id, deeplink=deeplink_info(answer.deeplink))
    except ScrapeHTTPException as error:
        # The council's site failed and nothing was cached (a cache hit never
        # scrapes): send the user to the council's page, as for an unwired council.
        if error.fallback is None:
            raise
        response.headers[SCRAPE_FAILURE_HEADER] = error.failure or "error"
        return ScheduleResponse(uprn=uprn, council=meta.id, deeplink=deeplink_info(error.fallback))
    return ScheduleResponse(
        uprn=uprn,
        council=meta.id,
        cached=cached,
        cached_at=entry.last_success if cached else None,
        dates=_dates(meta.id, ((c["date"], c["type"], c.get("icon")) for c in entry.collections)),
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
    try:
        ics_bytes = await cache.read_ics_bytes(uprn)
    except BlobStoreError:
        logger.exception("ICS cache read failed for %s", uprn)
        ics_bytes = None
    if ics_bytes is None:
        raise HTTPException(
            status_code=503,
            detail="Calendar temporarily unavailable. Please try again later.",
        )
    # Shared caches (Vercel's CDN, Cloudflare) hold it for 12 h: the data only
    # changes on the nightly refresh, and it keeps polls off the function.
    headers = {"Cache-Control": "public, s-maxage=43200"}
    if attachment:
        headers["Content-Disposition"] = f'attachment; filename="bins-{_safe_uprn_filename(uprn)}.ics"'
    return Response(content=ics_bytes, media_type="text/calendar", headers=headers)


async def turnstile_passed(request: Request) -> bool:
    """Whether the request may use the address API: always without
    TURNSTILE_SECRET, else only with a valid `X-Turnstile-Token`. No token is
    False; a token that fails is a 403, so the frontend can retry the widget."""
    if not config.TURNSTILE_SECRET:
        return True
    token = request.headers.get("X-Turnstile-Token")
    if not token:
        return False
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
    return True


async def find(request: Request, postcode: str) -> FindResponse:
    """The postcode's council and, when we serve it, its addresses.

    An unwired council, or a wired one whose scraper can never run without a
    browser (captcha, login), answers with its deeplink and no address step,
    so the address API is only called for a council we can look up. The
    address step alone sits behind Turnstile: without a token `addresses` is
    None and the council still answers.
    """
    council, council_name, candidates, lad_code = await resolve_council(
        request, request.app.state.council_lookup, postcode
    )

    deeplink = None
    if lad_code and not council:
        target = deeplink_service.resolve(lad_code)
        if target:
            deeplink = deeplink_info(target)
    elif council:
        meta = request.app.state.registry.get(council)
        if meta is not None and meta.needs_browser:
            target = deeplink_service.for_needs_browser(meta, meta.needs_browser)
            if target:
                council, deeplink = None, deeplink_info(target)

    return FindResponse(
        postcode=postcode.strip().upper(),
        council=council,
        council_name=council_name,
        candidates=candidates,
        deeplink=deeplink,
        addresses=await _addresses_for(request, postcode) if council else [],
    )


async def _addresses_for(request: Request, postcode: str) -> list[AddressResult] | None:
    if not await turnstile_passed(request):
        return None
    return await search_addresses(postcode)


async def search_addresses(postcode: str) -> list[AddressResult]:
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
    return [AddressResult(**r) for r in results]
