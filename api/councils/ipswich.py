"""Ipswich: fetches a schedule by its numeric location ID and parses month headings and bin-day lists."""

from __future__ import annotations

import re
from datetime import date

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_SCHEDULE_URL = "https://app.ipswich.gov.uk/bin-collection-better-recycling/months/{}"

_BIN_MAP: tuple[tuple[str, str], ...] = (
    ("food", "Food Waste"),
    ("black", "General Waste"),
    ("blue", "Recycling (Blue bin)"),
    ("green", "Recycling (Green bin)"),
    ("brown", "Garden Waste"),
)

_ORDINAL_RE = re.compile(r"(\d+)(?:st|nd|rd|th)", re.IGNORECASE)

_MONTH_HEADING_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{4})$",
    re.IGNORECASE,
)

_MONTH_NAMES: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _classify(dt_text: str) -> str:
    """Return the display name for a bin description."""
    lower = dt_text.lower()
    for keyword, name in _BIN_MAP:
        if keyword in lower:
            return name
    return dt_text.strip().title()


def _parse_days(dd_text: str) -> list[int]:
    """Parse a comma-separated ordinal list, e.g. '4th, 11th, 18th'."""
    return [int(match.group(1)) for match in _ORDINAL_RE.finditer(dd_text)]


class Ipswich(Scraper):
    meta = Meta(
        title="Ipswich Borough Council",
        url="https://www.ipswich.gov.uk",
        lads=("E07000202",),
        cases={"High Street (id 549)": {"location_id": "549"}},
    )
    requires = frozenset({"location_id"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        try:
            location_id = int(address.need("location_id"))
        except ValueError as exc:
            raise InputError("location_id must be numeric") from exc

        response = await http.get(
            _SCHEDULE_URL.format(location_id),
            timeout=30,
            check=False,
        )
        if response.status_code == 404:
            raise AddressNotFound(f"Ipswich has no schedule for location_id {location_id}")
        if response.status_code >= 400:
            raise UpstreamError(f"HTTP {response.status_code} from {response.url}")

        page = soup(response.text)
        article = page.find("article")
        if article is None:
            raise AddressNotFound(f"Ipswich has no schedule for location_id {location_id}")

        collections: list[Collection] = []
        current_month: int | None = None
        current_year: int | None = None

        for element in article.find_all(["h4", "dl"]):
            if element.name == "h4":
                match = _MONTH_HEADING_RE.match(element.get_text(strip=True))
                if match:
                    current_month = _MONTH_NAMES[match.group(1).lower()]
                    current_year = int(match.group(2))
            elif element.name == "dl":
                if current_month is None or current_year is None:
                    continue

                for dt, dd in zip(
                    element.find_all("dt"), element.find_all("dd"), strict=False
                ):
                    bin_name = _classify(dt.get_text(strip=True))
                    for day in _parse_days(dd.get_text(strip=True)):
                        try:
                            collection_date = date(current_year, current_month, day)
                        except ValueError:
                            continue
                        collections.append(Collection(collection_date, bin_name))

        if not collections:
            raise AddressNotFound(f"Ipswich has no schedule for location_id {location_id}")

        return collections


SCRAPER = Ipswich()
