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
from api.services.council_lookup import LookupDatabaseError, PostcodeNotFoundError
from api.services.models import CouncilCandidate
from api.services.scrape_lock import acquire, release
from api.services.scraper_registry import ScraperTimeoutError

logger = logging.getLogger(__name__)


def map_scrape_exception(council: str, exc: Exception) -> HTTPException:
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

    entry = await cache.read(uprn)
    if entry is not None and entry.last_success is not None:
        return entry, True

    lock_acquired = await acquire(redis_client, uprn)
    if not lock_acquired:
        deadline = asyncio.get_event_loop().time() + config.SCRAPE_LOCK_MAX_WAIT_S
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(config.SCRAPE_LOCK_POLL_INTERVAL_S)
            entry = await cache.read(uprn)
            if entry is not None and entry.last_success is not None:
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
            raise map_scrape_exception(council, exc) from exc

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
        raise map_scrape_exception(council, exc) from exc
    return collections


async def resolve_council(
    request: Request, lookup, postcode: str
) -> tuple[str | None, str | None, list[CouncilCandidate], str | None]:
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
                "Postcode resolved to unwired council %s (%s) — deeplink",
                authority.name,
                authority.lad_code,
                extra=log_extra,
            )
            return None, authority.name, [], authority.lad_code
        return authority.slug, authority.name, [], authority.lad_code

    logger.info(
        "Ambiguous postcode: %d candidate councils",
        len(authorities),
        extra=log_extra,
    )
    candidates = [
        CouncilCandidate(slug=a.slug, name=a.name, homepage_url=a.homepage_url)
        for a in authorities
        if a.slug
    ]
    return None, None, candidates, None
