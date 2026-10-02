"""`/api/v1/calendar/{uprn}?council=`: the one v1 route kept, for calendar
subscriptions made before v2. It answers with the v2 feed itself rather than a
redirect, since not every calendar app follows redirects on a subscription.
`council` may be a LAD code or an old scraper ID; the registry resolves both."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from api.routes import schedule

router = APIRouter(include_in_schema=False)


@router.get("/calendar/{uprn}", response_class=Response)
async def calendar(
    request: Request,
    uprn: str,
    council: str = Query(),
):
    return await schedule.calendar_response(request, uprn, council, attachment=True)
