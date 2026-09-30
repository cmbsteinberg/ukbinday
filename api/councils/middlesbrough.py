"""Middlesbrough: resolve a house number through Recollect, then read its next collection."""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
)

_API = "https://api.eu.recollect.net/api/areas/MiddlesbroughUK/services/50005"
_CALENDAR_URL = (
    f"{_API}/pages/en-GB/place_calendar.json"
    "?widget_config=%7B%22area%22%3A%22MiddlesbroughUK%22%2C%22name%22%3A%22calendar%22%2C%22base%22%3A%22https%3A%2F%2Frecollect.net%22%2C%22third_party_cookie_enabled%22%3A1%2C%22place_not_found_in_guest%22%3A0%2C%22is_guest_service%22%3A0%7D"
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)


def _extract_next_collection(
    payload: dict[str, Any],
) -> tuple[date | str | None, list[dict[str, Any]]]:
    sections = payload.get("sections", [])
    section = next(
        (item for item in sections if item.get("title") == "Next Collection"),
        None,
    )
    if not section:
        return None, []

    rows = section.get("rows", [])
    next_date: date | str | None = None
    if rows and rows[0].get("type") == "html":
        html = rows[0].get("html", "")
        match = re.search(r"<strong>(.*?)</strong>", html, flags=re.I | re.S)
        if match:
            date_text = match.group(1).strip()
            try:
                next_date = datetime.strptime(date_text, "%A, %B %d, %Y").date()
            except ValueError:
                next_date = date_text

    bins: list[dict[str, Any]] = []
    for row in rows[1:]:
        if row.get("type") == "rich-content":
            label = row.get("label") or row.get("html")
            flag = (row.get("data") or {}).get("flag")
            if label or flag:
                bins.append({"label": label, "flag": flag})

    return next_date, bins


def _parse_fallback_date(value: str) -> date | None:
    if "-" in value:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
    if "/" in value:
        try:
            return datetime.strptime(value, "%d/%m/%Y").date()
        except ValueError:
            return None
    return None


class Middlesbrough(Scraper):
    meta = Meta(
        title="Middlesbrough",
        url="https://www.middlesbrough.gov.uk/recycling-and-rubbish/bin-collection-dates/",
        lads=("E06000002",),
        cases={},
    )
    requires = frozenset({"house_number"})
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        house_number = address.need("house_number")
        params = {
            "q": house_number,
            "locale": "en-GB",
            "_": str(int(time.time() * 1000)),
        }
        response = await http.get(f"{_API}/address-suggest", params=params)

        place_id = None
        for item in response.json():
            if "place_id" in item:
                place_id = item["place_id"]
                break
        if not place_id:
            raise AddressNotFound("Middlesbrough could not find the address")

        params = {
            "q": house_number,
            "locale": "en-GB",
            "_": str(int(time.time() * 1000)),
        }
        response = await http.get(
            _CALENDAR_URL,
            params=params,
            headers={"x-recollect-place": place_id + ":50005"},
        )

        collection_date, bins = _extract_next_collection(response.json())
        if not collection_date or not bins:
            return []

        day = (
            collection_date
            if isinstance(collection_date, date)
            else _parse_fallback_date(collection_date)
        )
        if day is None:
            return []

        collections = []
        for item in bins:
            bin_type = item.get("label") or item.get("flag")
            if bin_type:
                collections.append(Collection(day, bin_type))
        return collections


SCRAPER = Middlesbrough()
