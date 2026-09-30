"""Thurrock: match a street and town to its collection day and round, then expand weekly dates."""

from __future__ import annotations

import re
from datetime import date, datetime

from dateutil.rrule import FR, MO, SA, SU, TH, TU, WE, WEEKLY, rrule, weekday

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_TITLE = "Thurrock"
_URL = "https://www.thurrock.gov.uk/"
_STREETS_BASE_URL = "https://www.thurrock.gov.uk/household-bin-collection-days/street-names"
_API_URL = "https://www.thurrock.gov.uk/household-bin-collection-days/household-bin-collection-weeks"

_WEEKDAYS: dict[str, weekday] = {
    "monday": MO,
    "tuesday": TU,
    "wednesday": WE,
    "thursday": TH,
    "friday": FR,
    "saturday": SA,
    "sunday": SU,
}
_DATE_RANGE_RE = re.compile(r"\s*[-–—]\s*")
_BIN_SPLIT_RE = re.compile(r"\s*/\s*|\s+and\s+")


def _streets_url(street: str) -> str:
    first = street[0].lower()
    if first == "a":
        return _STREETS_BASE_URL
    return f"{_STREETS_BASE_URL}-{first}"


def _parse_date_range(range_str: str) -> tuple[date, date]:
    """Parse a date range such as '18 May - 22 May'."""
    now = datetime.now()
    parts = _DATE_RANGE_RE.split(range_str.strip())
    if len(parts) != 2:
        raise ValueError(f"Cannot parse date range: {range_str!r}")

    start_str, end_str = parts
    start_date = datetime.strptime(
        start_str.strip() + f" {now.year}", "%d %B %Y"
    ).date()
    end_date = datetime.strptime(
        end_str.strip() + f" {now.year}", "%d %B %Y"
    ).date()
    if start_date.month == 12 and end_date.month == 1:
        end_date = end_date.replace(year=start_date.year + 1)
    return start_date, end_date


class Thurrock(Scraper):
    meta = Meta(
        title=_TITLE,
        url=_URL,
        lads=("E06000034",),
        cases={
            "Camden Close Chadwell St Mary": {
                "street": "Camden Close",
                "town": "Chadwell St Mary",
            },
            "Abberton Way West Thurrock": {
                "street": "Abberton Way",
                "town": "West Thurrock",
            },
        },
    )
    requires = frozenset({"street", "town"})
    transport = __import__("api.councils._base", fromlist=["Transport"]).Transport.CURL_CFFI
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        street_name = address.need("street")
        town_name = address.need("town")

        r = await http.get(_streets_url(street_name))
        page = soup(r.text.replace("&nbsp;", " ").replace("\xa0", " "))
        table = page.select_one("table")
        if not table:
            raise UpstreamError("Thurrock street, town table not found")

        towns: list[str] = []
        streets: list[str] = []
        day_str: str | None = None
        round_name: str | None = None
        town_match = False
        street_match = False

        for row in table.select("tr")[1:]:
            cells = row.select("td")
            if len(cells) != 3:
                continue
            parts = cells[0].get_text().strip().rsplit(", ", 1)
            if len(parts) != 2:
                continue
            listed_street, listed_town = parts

            towns.append(listed_town.strip().casefold())
            streets.append(listed_street.strip().casefold())
            if street_name.casefold() in listed_street.casefold():
                street_match = True
            if town_name.casefold() in listed_town.casefold():
                town_match = True
            if street_match and town_match:
                day_str = cells[1].get_text().strip()
                round_name = cells[2].get_text().strip()
                break

        if not day_str:
            if town_match:
                raise AddressNotFound(
                    f"No street matching {street_name!r} in {town_name!r}",
                    streets,
                )
            raise AddressNotFound(f"No town matching {town_name!r}", towns)

        day = _WEEKDAYS.get(day_str.lower())
        if day is None:
            raise UpstreamError(f"Thurrock returned an invalid collection weekday: {day_str}")

        r = await http.get(_API_URL)
        page = soup(r.text.replace("\xa0", " "))
        table = page.select_one("table")
        if not table:
            raise UpstreamError("Thurrock collection table not found")

        collections: list[Collection] = []
        for row in table.select("tr")[1:]:
            cells = row.select("td")
            if len(cells) != 3:
                raise UpstreamError("Thurrock returned an invalid collection table row")
            try:
                start_date, end_date = _parse_date_range(cells[0].get_text().strip())
            except ValueError as exc:
                raise UpstreamError("Thurrock returned an invalid collection date range") from exc

            bin_text = cells[1 if round_name == "A" else 2].get_text().strip()
            bins = [bin_type.strip() for bin_type in _BIN_SPLIT_RE.split(bin_text) if bin_type.strip()]

            for bin_type in bins:
                for collection_date in rrule(
                    WEEKLY,
                    dtstart=start_date,
                    until=end_date,
                    byweekday=day,
                ):
                    collections.append(Collection(collection_date.date(), bin_type))

        return collections


SCRAPER = Thurrock()
