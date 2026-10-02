"""The schedule routes, shaped after the LocalGov Drupal waste collection module
(drupal.org/project/localgov_waste_collection), council in the path.

    /find?postcode=          the postcode's council and addresses
    /{lad}/view/{uprn}       the schedule: {uprn, council, cached, cached_at, dates, deeplink}
    /{lad}/subscribe/{uprn}  the ICS feed, for calendar subscriptions
    /{lad}/download/{uprn}   the ICS as a file download

The logic is in `schedule.py`. Deliberate deviations from Drupal: ISO dates,
a structured address list rather than a {uprn: address} map, and no
`weekly_collection` or `collection_time`, which no council source gives us
reliably.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response

from api.routes import schedule
from api.routes.internal import require_cron_secret
from api.services.models import FindResponse, ScheduleResponse
from api.services.rate_limiting import rate_limit

router = APIRouter()

LAD_PATH = Path(
    description="The council's ONS LAD code (e.g. E06000001), as /find returns it. "
    "Scraper IDs from before the switch to LAD codes still resolve.",
)


@router.get("/find", response_model=FindResponse)
async def find(
    request: Request,
    postcode: str = Query(description="The postcode to look up."),
    _rate_limit: None = Depends(rate_limit),
):
    """The postcode's council and its addresses, each with the UPRN to pass to /view.

    `council` is the LAD code when we serve the council. Otherwise `addresses`
    is empty and `deeplink` points at the council's own page, or `candidates`
    lists the councils a postcode straddles. Where Turnstile is configured the
    address list needs an `X-Turnstile-Token` header; without one `addresses`
    is null and the rest still answers."""
    return await schedule.find(request, postcode)


@router.get("/{lad}/view/{uprn}", response_model=ScheduleResponse)
async def view(
    request: Request,
    response: Response,
    uprn: str,
    lad: str = LAD_PATH,
    postcode: str | None = None,
    address: str | None = None,
    fresh: bool = Query(False, include_in_schema=False),
    _rate_limit: None = Depends(rate_limit),
):
    """Collection dates, ascending; a deeplink instead when we can't fetch them.

    Councils that need more than the UPRN (postcode, address label,
    property_id, usrn...) take it as query params; /councils lists them."""
    # `fresh` scrapes past the cache (scripts/vercel_probe.py), so it needs the cron secret
    if fresh:
        await require_cron_secret(request)
    return await schedule.get_schedule(request, response, uprn, lad, fresh=fresh)


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
    return await schedule.calendar_response(request, uprn, lad, attachment=False)


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
    return await schedule.calendar_response(request, uprn, lad, attachment=True)
