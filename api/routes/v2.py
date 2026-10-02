"""v2: routes shaped after the LocalGov Drupal waste collection module
(drupal.org/project/localgov_waste_collection), council in the path.

    /{lad}/find?postcode=    addresses for a postcode
    /{lad}/view/{uprn}       the schedule: {uprn, council, cached, cached_at, dates, deeplink}
    /{lad}/subscribe/{uprn}  the ICS feed, for calendar subscriptions
    /{lad}/download/{uprn}   the ICS as a file download

Same lookup, cache and calendar logic as v1 (`schedule.py`); only the shape
differs. Deliberate deviations from Drupal: ISO dates, a structured address
list rather than a {uprn: address} map, and no `weekly_collection` or
`collection_time`, which no council source gives us reliably.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import Response

from api.councils._base import colour_of
from api.routes.schedule import (
    SCRAPE_FAILURE_HEADER,
    calendar_response,
    get_schedule,
    search_addresses,
    verify_turnstile,
)
from api.services import deeplinks as deeplink_service
from api.services.bank_holidays import holiday_name
from api.services.models import (
    CollectionDateV2,
    CollectionItem,
    CollectionTypeV2,
    FindResponseV2,
    ScheduleResponseV2,
)
from api.services.rate_limiting import rate_limit

router = APIRouter(tags=["v2"])

LAD_PATH = Path(
    description="The council's ONS LAD code (e.g. E06000001), as /api/v1/council/{postcode} returns it. "
    "Scraper IDs from before the switch to LAD codes still resolve.",
)


def _dates(lad: str, collections: list[CollectionItem]) -> list[CollectionDateV2]:
    return [
        CollectionDateV2(
            date=c.date,
            holiday=holiday_name(lad, c.date),
            type=CollectionTypeV2(label=c.type, colour=colour_of(c.type), icon=c.icon),
        )
        for c in sorted(collections, key=lambda c: (c.date, c.type))
    ]


@router.get("/{lad}/find", response_model=FindResponseV2)
async def find(
    request: Request,
    lad: str = LAD_PATH,
    postcode: str = Query(description="The postcode to list addresses for."),
    _rate_limit: None = Depends(rate_limit),
    _turnstile: None = Depends(verify_turnstile),
):
    """Addresses for a postcode, each with the UPRN to pass to /view."""
    meta = request.app.state.registry.get(lad)
    if meta is not None:
        council = meta.id
    elif deeplink_service.resolve_by_council_param(lad) is not None:
        council = lad  # unwired: /view answers with its deeplink
    else:
        raise HTTPException(status_code=404, detail="No council answers to this code.")
    found = await search_addresses(postcode)
    return FindResponseV2(council=council, postcode=found.postcode, addresses=found.addresses)


@router.get("/{lad}/view/{uprn}", response_model=ScheduleResponseV2)
async def view(
    request: Request,
    response: Response,
    uprn: str,
    lad: str = LAD_PATH,
    postcode: str | None = None,
    address: str | None = None,
    _rate_limit: None = Depends(rate_limit),
):
    """Collection dates, ascending; a deeplink instead when we can't fetch them.

    Councils that need more than the UPRN (postcode, address label,
    property_id, usrn...) take it as query params, as on /api/v1/lookup."""
    schedule = await get_schedule(request, uprn, lad)
    if schedule.failure:
        response.headers[SCRAPE_FAILURE_HEADER] = schedule.failure
    return ScheduleResponseV2(
        uprn=uprn,
        council=schedule.council,
        cached=schedule.cached,
        cached_at=schedule.cached_at,
        dates=_dates(schedule.council, schedule.collections),
        deeplink=schedule.deeplink,
    )


@router.get("/{lad}/subscribe/{uprn}", response_class=Response)
async def subscribe(
    request: Request,
    uprn: str,
    lad: str = LAD_PATH,
    postcode: str | None = None,
    address: str | None = None,
    _rate_limit: None = Depends(rate_limit),
):
    """The ICS feed, for a calendar subscription (webcal)."""
    return await calendar_response(request, uprn, lad, attachment=False)


@router.get("/{lad}/download/{uprn}", response_class=Response)
async def download(
    request: Request,
    uprn: str,
    lad: str = LAD_PATH,
    postcode: str | None = None,
    address: str | None = None,
    _rate_limit: None = Depends(rate_limit),
):
    """The ICS as a file download."""
    return await calendar_response(request, uprn, lad, attachment=True)
