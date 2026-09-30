"""Nuneaton and Bedworth: search the street directory, then derive bin dates from its calendar PDF link."""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import quote_plus

from bs4 import Tag

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

_BASE_URL = "https://www.nuneatonandbedworth.gov.uk/"
_HEADERS = {
    "Origin": "https://www.nuneatonandbedworth.gov.uk/",
    "Referer": "https://www.nuneatonandbedworth.gov.uk/",
    "User-Agent": "Mozilla/5.0",
}
_CYCLE_FIRST_MONDAY = date(2026, 10, 5)
_CYCLE_END = date(2027, 9, 30)
_NO_GREEN_FROM = date(2027, 1, 17)
_NO_GREEN_TO = date(2027, 1, 31)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")


def _calendar_dates(filename: str) -> dict[str, list[date]]:
    match = re.fullmatch(r"bin-calendar-(\w+)-([ab])", filename)
    if not match or match.group(1) not in _WEEKDAYS:
        raise UpstreamError(f"Unknown bin calendar: {filename}")

    weekday = _WEEKDAYS.index(match.group(1))
    black_parity = 0 if match.group(2) == "a" else 1

    black: list[date] = []
    brown: list[date] = []
    green: list[date] = []
    day = _CYCLE_FIRST_MONDAY - timedelta(days=7) + timedelta(days=weekday)
    while day <= _CYCLE_END:
        if day >= date(2026, 10, 1):
            week = (day - _CYCLE_FIRST_MONDAY).days // 7
            if week % 2 == black_parity:
                black.append(day)
            else:
                brown.append(day)
                if not _NO_GREEN_FROM <= day <= _NO_GREEN_TO:
                    green.append(day)
        day += timedelta(days=7)

    return {"Black Bin": black, "Brown Bin": brown, "Green Bin": green}


class NuneatonAndBedworth(Scraper):
    meta = Meta(
        title="Nuneaton and Bedworth",
        url="https://www.nuneatonandbedworth.gov.uk",
        lads=("E07000219",),
        cases={},
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        search = address.street or address.house_number
        if not search:
            raise InputError("Nuneaton and Bedworth needs a street or house number")

        search_query = (
            "directory/search?directoryID=3&showInMap=&keywords="
            f"{quote_plus(search)}&search=Search+directory"
        )
        search_response = await http.get(
            _BASE_URL + search_query,
            headers=_HEADERS,
            check=False,
        )
        if search_response.status_code != 200:
            raise UpstreamError("Failed to retrieve search results.")

        page = soup(search_response.content)
        street_link_tags = page.find_all("a", class_="list__link")
        street_name = search.strip().lower()
        matches = [
            tag
            for tag in street_link_tags
            if street_name in tag.get_text().lower()
        ]

        if len(matches) > 1:
            exact = [
                tag for tag in matches if tag.get_text().strip().lower() == street_name
            ]
            if len(exact) == 1:
                matches = exact

        if not matches:
            raise AddressNotFound("Street URL not found.")
        if len(matches) > 1:
            raise AddressNotFound("Multiple street URLs found. Please refine your search.")

        street_link = matches[0]
        if not isinstance(street_link, Tag) or not isinstance(street_link.get("href"), str):
            raise UpstreamError("Street search result has no link.")

        full_url = _BASE_URL.rstrip("/") + street_link["href"]
        bin_day_response = await http.get(full_url, headers=_HEADERS, check=False)
        if bin_day_response.status_code != 200:
            raise UpstreamError("Failed to retrieve bin data.")

        bin_page = soup(bin_day_response.content)
        download_link = bin_page.find("a", {"href": re.compile(r"/downloads/file")})
        if not isinstance(download_link, Tag) or not isinstance(download_link.get("href"), str):
            raise UpstreamError("Bin data download link not found.")

        filename = download_link["href"].split("/")[-1]
        dates_by_type = _calendar_dates(filename)
        return [
            Collection(day, bin_type)
            for bin_type, dates in dates_by_type.items()
            for day in dates
        ]


SCRAPER = NuneatonAndBedworth()
