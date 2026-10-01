from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import HTTPException, Request

from api import config
from api.compat.hacs.exceptions import (
    SourceArgumentException,
    SourceArgumentExceptionMultiple,
)
from api.councils._base import AddressNotFound, InputError, NeedsBrowser, UpstreamError
from api.services import deeplinks
from api.services.council_lookup import LookupDatabaseError, PostcodeNotFoundError
from api.services.models import CouncilCandidate
from api.services.scrape_lock import acquire, release
from api.services.scraper_registry import ScraperTimeoutError

logger = logging.getLogger(__name__)

_INPUT_REJECTED = (
    "The details provided don't match what this council's system expects. "
    "Please check your UPRN and postcode are correct."
)


class ScrapeHTTPException(HTTPException):
    """A failed scrape, as an HTTP error, plus what a caller may answer instead.

    - `suggestions`: the council's own address labels (AddressNotFound); api/main.py
      renders them next to `detail` in the 422 body.
    - `failure`: for a 503/504, the kind: "network" (site unreachable or erroring),
      "timeout", or "error" (an old scraper crashed).
    - `fallback`: the deeplink /lookup answers with instead of the 503/504, when
      the council's site failed and nothing was cached. /calendar can't show a
      deeplink, so it raises the error as is.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        suggestions: tuple[str, ...] = (),
        failure: str | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.suggestions = list(suggestions)
        self.failure = failure
        self.fallback: deeplinks.Deeplink | None = None


class DeeplinkAnswer(Exception):
    """The scraper needs a person at a browser: answer with this deeplink, not an error."""

    def __init__(self, deeplink: deeplinks.Deeplink) -> None:
        super().__init__(deeplink.reason)
        self.deeplink = deeplink


def map_scrape_exception(council: str, exc: Exception) -> ScrapeHTTPException:
    if isinstance(exc, (SourceArgumentException, SourceArgumentExceptionMultiple, InputError)):
        suggestions = exc.suggestions if isinstance(exc, AddressNotFound) else ()
        logger.info("Scraper %s rejected the input: %s", council, exc)
        return ScrapeHTTPException(422, _INPUT_REJECTED, suggestions=suggestions)
    if isinstance(exc, ScraperTimeoutError):
        return ScrapeHTTPException(
            504,
            "Your council's website is taking too long to respond. "
            "Please try again later.",
            failure="timeout",
        )
    if isinstance(exc, (httpx.HTTPError, TimeoutError, UpstreamError)):
        if isinstance(exc, UpstreamError):
            logger.info("Scraper %s upstream error: %s", council, exc)
        return ScrapeHTTPException(
            503,
            "We couldn't reach your council's website. "
            "The site may be temporarily down \u2014 please try again later.",
            failure="network",
        )
    logger.exception("Scraper %s failed", council)
    return ScrapeHTTPException(
        503,
        "Something went wrong while fetching your collection schedule. "
        "Please try again later.",
        failure="error",
    )


def is_cacheable_uprn(uprn: str) -> bool:
    """A UPRN that can key the ICS cache. "0" (or any all-zero/non-numeric
    placeholder) is what callers send for address-only councils; caching on it
    would hand every later address-only lookup the first one's schedule."""
    return uprn.isdigit() and uprn.strip("0") != ""


def build_scrape_params(
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


async def get_or_scrape(
    request: Request, uprn: str, council: str, params: dict[str, str]
):
    cache = request.app.state.ics_cache
    registry = request.app.state.registry
    redis_client = getattr(request.app.state, "redis", None)

    def _hit(entry) -> bool:
        # A sidecar written by a different scraper is not this council's data.
        # Compare resolved IDs: a sidecar may carry an alias of `council`.
        return (
            entry is not None
            and entry.last_success is not None
            and registry.canonical_id(entry.scraper) == registry.canonical_id(council)
        )

    entry = await cache.read(uprn)
    if _hit(entry):
        return entry, True

    lock_acquired = await acquire(redis_client, uprn)
    if not lock_acquired:
        deadline = asyncio.get_event_loop().time() + config.SCRAPE_LOCK_MAX_WAIT_S
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(config.SCRAPE_LOCK_POLL_INTERVAL_S)
            entry = await cache.read(uprn)
            if _hit(entry):
                return entry, True
        raise HTTPException(
            status_code=503,
            detail="Another request is already fetching this schedule. "
            "Please try again in a few seconds.",
        )

    try:
        try:
            collections = await registry.invoke(council, params)
            registry.record_success(council)
        except Exception as exc:
            registry.record_failure(council, str(exc))
            await cache.record_failure(
                uprn, str(exc), scraper_id=council, params=params
            )
            raise _answer_for(registry, council, exc) from exc

        entry = await cache.write(uprn, council, params, collections)
        return entry, False
    finally:
        await release(redis_client, uprn)


async def live_scrape(request: Request, council: str, params: dict[str, str]):
    registry = request.app.state.registry
    try:
        collections = await registry.invoke(council, params)
        registry.record_success(council)
    except Exception as exc:
        registry.record_failure(council, str(exc))
        raise _answer_for(registry, council, exc) from exc
    return collections


def needs_browser_deeplink(meta, reason: str) -> DeeplinkAnswer | HTTPException:
    """What to raise for a council that needs a browser: its deeplink, or a 503
    when there's no URL to send anyone to."""
    target = deeplinks.for_needs_browser(meta, reason)
    if target is None:
        return HTTPException(
            status_code=503,
            detail="Something went wrong while fetching your collection schedule. "
            "Please try again later.",
        )
    return DeeplinkAnswer(target)


def _answer_for(registry, council: str, exc: Exception) -> Exception:
    """What a failed scrape answers with.

    NeedsBrowser: a deeplink (meta.url first). Otherwise the mapped HTTP error,
    with a GOV.UK-first deeplink attached as its `fallback` when the council's
    site failed: any 503/504 from an old scraper; UpstreamError or a timeout from
    a council module (anything else escaping a module is a bug, not the site).
    """
    meta = registry.get(council)
    if isinstance(exc, NeedsBrowser) and meta is not None:
        logger.info("Scraper %s needs a browser: %s", council, exc)
        return needs_browser_deeplink(meta, str(exc))
    error = map_scrape_exception(council, exc)
    site_failed = error.failure is not None and (
        meta is None or meta.scraper is None or isinstance(exc, (UpstreamError, ScraperTimeoutError))
    )
    if site_failed and meta is not None:
        error.fallback = deeplinks.for_upstream_failure(meta)
    return error


async def resolve_council(
    request: Request, lookup, postcode: str
) -> tuple[str | None, str | None, list[CouncilCandidate], str | None]:
    """(council ID, name, candidates, LAD code) for a postcode.

    The council ID is the LAD code when the registry serves that LAD, else
    None (the caller answers with the LAD's deeplink).
    """
    registry = request.app.state.registry

    def council_id(authority) -> str | None:
        meta = registry.get(authority.lad_code)
        return meta.id if meta is not None else None

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
        cid = council_id(authority)
        if cid is None:
            logger.info(
                "Postcode resolved to unwired council %s (%s) — deeplink",
                authority.name,
                authority.lad_code,
                extra=log_extra,
            )
        return cid, authority.name, [], authority.lad_code

    logger.info(
        "Ambiguous postcode: %d candidate councils",
        len(authorities),
        extra=log_extra,
    )
    candidates = [
        CouncilCandidate(slug=cid, name=a.name, homepage_url=a.homepage_url)
        for a in authorities
        if (cid := council_id(a)) is not None
    ]
    return None, None, candidates, None
