"""Westminster: fetch a street's rubbish and recycling tables by USRN and project weekly collection days."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from bs4 import BeautifulSoup, Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    soup,
)

_API_URL = "https://transact.westminster.gov.uk/env/streetreport.aspx?Street=NA&USRN={usrn}"
_HORIZON_DAYS = 365
_RUBBISH_TYPE = "Residential rubbish and commercial waste"

_WEEKDAYS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def _parse_days(text: str) -> set[int]:
    """Expand a day cell (e.g. 'Tue, Fri', 'Mon-Fri') into weekday() indices."""
    text = text.replace("\xa0", " ")
    result: set[int] = set()
    for token in text.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if "-" in token:
            start, _, end = token.partition("-")
            start_day = _WEEKDAYS.get(start.strip()[:3])
            end_day = _WEEKDAYS.get(end.strip()[:3])
            if start_day is None or end_day is None:
                continue
            if start_day <= end_day:
                result.update(range(start_day, end_day + 1))
            else:
                result.update(range(start_day, 7))
                result.update(range(end_day + 1))
        else:
            weekday = _WEEKDAYS.get(token[:3])
            if weekday is not None:
                result.add(weekday)
    return result


def _column_index(table: Tag) -> dict[str, int]:
    """Map lowercased header-cell text to column index for a table's first row."""
    header = table.find("tr")
    cols: dict[str, int] = {}
    if not isinstance(header, Tag):
        return cols
    for index, cell in enumerate(header.find_all(["th", "td"])):
        cols[cell.get_text(strip=True).lower()] = index
    return cols


def _data_rows(table: Tag) -> list[Tag]:
    """All rows after the header row."""
    return table.find_all("tr")[1:]


def _days_from_row(cells: list[Tag], cols: dict[str, int]) -> set[int]:
    """Union of Week Days and Weekend Days cells for one row."""
    days: set[int] = set()
    for key in ("week days", "weekend days"):
        index = cols.get(key)
        if index is not None and index < len(cells):
            days |= _parse_days(cells[index].get_text())
    return days


def _extract_pairs(page: BeautifulSoup) -> set[tuple[str, int]]:
    """Parse the rubbish and recycling panels into deduplicated waste-type/weekday pairs."""
    pairs: set[tuple[str, int]] = set()

    rubbish = page.find("div", id="pnlrubbishcollection")
    if isinstance(rubbish, Tag):
        table = rubbish.find("table")
        if isinstance(table, Tag):
            cols = _column_index(table)
            for row in _data_rows(table):
                cells = row.find_all(["td", "th"])
                if len(cells) != len(cols):
                    continue
                for weekday in _days_from_row(cells, cols):
                    pairs.add((_RUBBISH_TYPE, weekday))

    recycling = page.find("div", id="pnlrecyclingcollections")
    if isinstance(recycling, Tag):
        table = recycling.find("table")
        if isinstance(table, Tag):
            cols = _column_index(table)
            service_description = cols.get("service description")
            for row in _data_rows(table):
                cells = row.find_all(["td", "th"])
                if len(cells) != len(cols):
                    continue
                if service_description is None or service_description >= len(cells):
                    continue
                waste_type = cells[service_description].get_text(strip=True)
                if not waste_type:
                    continue
                for weekday in _days_from_row(cells, cols):
                    pairs.add((waste_type, weekday))

    return pairs


class Westminster(Scraper):
    meta = Meta(
        title="Westminster City Council",
        url="https://www.westminster.gov.uk",
        lads=("E09000033",),
        cases={
            "Shirland Mews (short street)": {"usrn": "8400172"},
            "Shirland Road (long street)": {"usrn": "8400243"},
        },
    )
    requires = frozenset({"usrn"})
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        usrn = address.need("usrn")
        response = await http.get(
            _API_URL.format(usrn=quote(usrn)),
            timeout=30,
        )

        pairs = _extract_pairs(soup(response.text))
        if not pairs:
            raise AddressNotFound(
                f"No collections found for USRN '{usrn}'. Check the USRN is correct."
            )

        today = date.today()
        horizon_end = today + timedelta(days=_HORIZON_DAYS)
        collections: list[Collection] = []
        for waste_type, weekday in pairs:
            offset = (weekday - today.weekday()) % 7
            collection_date = today + timedelta(days=offset)
            while collection_date <= horizon_end:
                collections.append(Collection(collection_date, waste_type))
                collection_date += timedelta(days=7)

        return collections


SCRAPER = Westminster()
