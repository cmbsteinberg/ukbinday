"""Chelmsford: search by postcode, match the property, then read its collection-round calendar."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

from bs4 import Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    find_tag,
    match_address,
    parse_ics,
    soup,
)

_BASE_URL = "https://www.chelmsford.gov.uk/bins-and-recycling/check-your-collection-day/"
_CALENDAR_ROOT = "https://www.chelmsford.gov.uk/bins-and-recycling/check-your-collection-day/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_ROUND_PATTERN = re.compile(r"(Monday|Tuesday|Wednesday|Thursday|Friday)\s+([AB])")


def _round_from_row(row: Tag) -> tuple[str, str] | None:
    match = _ROUND_PATTERN.search(row.get_text())
    if match is None:
        return None
    return match.group(1).lower(), match.group(2).lower()


class Chelmsford(Scraper):
    meta = Meta(
        title="Chelmsford",
        url=_BASE_URL,
        lads=("E07000070",),
        cases={},
    )
    requires = frozenset({"postcode", "house_number"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        house_number = address.need("house_number")

        response = await http.get(_BASE_URL, timeout=30)
        page = soup(response.text)
        input_el = page.find("input", id=re.compile(r"\d+_keyword"))
        if input_el is None or not input_el.get("id"):
            raise UpstreamError("Could not locate postcode input on Chelmsford's search page")
        form_id = input_el["id"].split("_")[0]

        search_url = f"{_BASE_URL}?{form_id}_keyword={quote(postcode)}#search-{form_id}"
        response = await http.get(search_url, timeout=30)
        page = soup(response.text)

        table = page.find("table", class_="directories-table__table")
        if table is None:
            table = page.find("table")

        calendar_url: str | None = None
        if isinstance(table, Tag):
            rows = [
                row for row in table.find_all("tr")
                if isinstance(row, Tag) and _round_from_row(row) is not None
            ]
            try:
                row = match_address(address, rows, text=lambda candidate: candidate.get_text(" ", strip=True))
                round_info = _round_from_row(row)
                if round_info is not None:
                    day, letter = round_info
                    calendar_url = f"{_CALENDAR_ROOT}{day}-{letter}-collection-calendar/"
            except AddressNotFound:
                pass  # not in the table: the page may list the address as a card instead

        if calendar_url is None:
            cards: list[Tag] = []
            for details in page.find_all("details"):
                if not isinstance(details, Tag):
                    continue
                link = details.find(
                    "a",
                    href=lambda href: isinstance(href, str) and "collection-calendar" in href,
                )
                if isinstance(link, Tag):
                    cards.append(details)
            card = match_address(
                address,
                cards,
                text=lambda candidate: candidate.get_text(" ", strip=True),
            )
            link = card.find(
                "a",
                href=lambda href: isinstance(href, str) and "collection-calendar" in href,
            )
            if isinstance(link, Tag):
                href = link.get("href")
                if isinstance(href, str):
                    calendar_url = href

        if calendar_url is None:
            raise AddressNotFound(f"Could not find collection round for address: {house_number}")

        response = await http.get(calendar_url, timeout=30)
        calendar_page = soup(response.text)
        ics_link = find_tag(calendar_page, "a", href=lambda href: isinstance(href, str) and href.lower().endswith(".ics"), what="Could not find Chelmsford's collection calendar")
        ics_url = ics_link.get("href")
        if not isinstance(ics_url, str):
            raise UpstreamError("Chelmsford's collection calendar link is invalid")

        calendar_response = await http.get(ics_url, timeout=30)
        events = await asyncio.to_thread(parse_ics, calendar_response.text, days=60)

        collections: list[Collection] = []
        for event in events:
            for bin_type in event.summary.split(","):
                if bin_type.strip():
                    collections.append(Collection(event.date, bin_type.strip()))
        return collections


SCRAPER = Chelmsford()
