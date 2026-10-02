"""Bolsover: an AchieveForms lookup by UPRN, returning the next four weekly collections."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_SESSION_URL = (
    "https://selfservice.bolsover.gov.uk/authapi/isauthenticated"
    "?uri=https%253A%252F%252Fselfservice.bolsover.gov.uk%252Fservice%252FCheck_your_Bin_Day"
    "&hostname=selfservice.bolsover.gov.uk&withCredentials=true"
)
_API_URL = "https://selfservice.bolsover.gov.uk/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://selfservice.bolsover.gov.uk/fillform/?iframe_id=fillform-frame-1&db_id=",
}
_GREEN_SUS_START = date(2024, 11, 8)
_GREEN_SUS_END = date(2025, 3, 18)


def _route_number(route: str) -> int | None:
    if route[:2] == "Mo":
        return 0
    if route[:2] == "Tu":
        return 1
    if route[:2] == "We":
        return 2
    if route[:2] == "Th":
        return 3
    if route[:2] == "Fr":
        return 4
    return None


def _determine_bin_collection(
    week_number: int,
    week_black: str,
    week_band_g: str,
    week_in_sus: bool,
) -> str:
    parity = "1" if week_number % 2 == 1 else "2"
    if week_black == parity:
        return "Black Bin"
    if week_band_g == parity:
        return "Burgundy Bin" if week_in_sus else "Burgundy Bin & Green Bin"
    return ""


class Bolsover(Scraper):
    meta = Meta(
        title="Bolsover",
        url="https://bolsover.gov.uk",
        lads=("E07000033",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        r = await http.get(_SESSION_URL)
        sid = r.json()["auth-session"]

        params = {
            "id": "6023d37e037c3",
            "repeat_against": "",
            "noRetry": "true",
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "_": str(int(time.time() * 1000)),
            "sid": sid,
        }
        r = await http.post(
            _API_URL,
            json={"formValues": {"Bin Collection": {"uprnLoggedIn": {"value": uprn}}}},
            headers=_HEADERS,
            params=params,
        )

        body = r.json()
        if body.get("status") == "error" or "integration" not in body:
            raise UpstreamError(f"Bolsover's lookup backend returned an error: {str(body)[:200]}")
        rows_data = body["integration"]["transformed"]["rows_data"].get("0")
        if not isinstance(rows_data, dict):
            raise UpstreamError("Invalid data returned from Bolsover's API")

        route = rows_data["Route"]
        route_number = _route_number(route)
        if route_number is None:
            raise UpstreamError(f"Invalid collection route from Bolsover: {route!r}")

        today = datetime.today()
        days_ahead = (route_number - today.weekday()) % 7
        week_one = today + timedelta(days=days_ahead)
        week_black = rows_data["WeekBlack"]
        week_band_g = rows_data["WeekBandG"]

        collections: list[Collection] = []
        for week_number in range(1, 5):
            collection_date = (week_one + timedelta(days=7 * (week_number - 1))).date()
            week_in_sus = _GREEN_SUS_START <= collection_date < _GREEN_SUS_END
            bin_types = _determine_bin_collection(
                week_number, week_black, week_band_g, week_in_sus
            )
            for bin_type in bin_types.split("&"):
                bin_type = bin_type.strip()
                if bin_type:
                    collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Bolsover()
