"""Bolsover: an AchieveForms lookup by UPRN, returning the next four weekly collections."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)
from api.councils._platforms.achieveforms import first_row, init_session, run_lookup

_HOSTNAME = "selfservice.bolsover.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URL = f"https://{_HOSTNAME}/service/Check_your_Bin_Day"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
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
        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URL)

        rows_data = first_row(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "6023d37e037c3",
                {"Bin Collection": {"uprnLoggedIn": {"value": uprn}}},
                no_retry="true",
                headers=_HEADERS,
            )
        )
        if rows_data is None:
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
