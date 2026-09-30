"""Ribble Valley: search the Jadu directory by postcode, then read the matched property's PDF calendar."""

from __future__ import annotations

import asyncio
import io
import re
from collections.abc import Sequence
from datetime import date, datetime
from html import unescape

import pdfplumber

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
)

BASE = "https://www.ribblevalley.gov.uk"
SEARCH_URL = BASE + "/directory/search"
MONTHS = [
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
]


def _bin_colour(cmyk: Sequence[float] | None) -> str | None:
    """Classify a calendar cell fill as green or blue."""
    if not cmyk or len(cmyk) != 4:
        return None
    return "green" if cmyk[2] > 0.5 else "blue"


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", unescape(text).upper()).split())


def _parse_calendar(pdf_bytes: bytes) -> list[Collection]:
    """Extract dated collections from a Ribble Valley calendar PDF."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        rects = [
            rect
            for rect in page.rects
            if rect.get("fill")
            and 19 <= rect["width"] <= 22
            and abs(rect["height"] - 19) < 2
        ]

    text = " ".join(word["text"] for word in words)
    match = re.search(r"([A-Za-z]+)\s+(\d{4})\s*-\s*([A-Za-z]+)\s+(\d{4})", text)
    if not match:
        raise ValueError("Could not read calendar year range from PDF")
    start_year = int(match.group(2))

    headers = [word for word in words if word["text"] in MONTHS]
    papers = [word for word in words if word["text"] == "P"]
    dates = [word for word in words if re.fullmatch(r"\d{1,2}", word["text"])]

    collections: list[Collection] = []
    for day_word in dates:
        candidates = [
            header
            for header in headers
            if 8 <= day_word["top"] - header["top"] <= 20
            and header["x0"] <= day_word["x0"] + 3
        ]
        if not candidates:
            continue
        header = max(candidates, key=lambda word: word["x0"])
        month = MONTHS.index(header["text"]) + 1
        year = start_year if month >= 4 else start_year + 1
        try:
            collection_date = date(year, month, int(day_word["text"]))
        except ValueError:
            continue

        center_x = (day_word["x0"] + day_word["x1"]) / 2
        rect = next(
            (
                item
                for item in rects
                if item["x0"] - 1 <= center_x <= item["x1"] + 1
                and 3 <= item["top"] - day_word["top"] <= 15
            ),
            None,
        )
        collections.append(Collection(collection_date, "Burgundy bin (general waste)"))
        if rect is None:
            continue

        kind = _bin_colour(rect.get("non_stroking_color"))
        if kind == "green":
            collections.append(Collection(collection_date, "Green bin (garden waste)"))
        elif kind == "blue":
            collections.append(Collection(collection_date, "Blue bin (recycling)"))

        has_paper = any(
            rect["x0"] <= (paper["x0"] + paper["x1"]) / 2 <= rect["x1"]
            and rect["top"] <= paper["top"] <= rect["bottom"]
            for paper in papers
        )
        if has_paper:
            collections.append(Collection(collection_date, "Paper and card (white sack)"))

    return collections


class RibbleValley(Scraper):
    meta = Meta(
        title="Ribble Valley Borough Council",
        url="https://www.ribblevalley.gov.uk/directory/1/find-your-bin-collection-day",
        lads=("E07000124",),
        cases={
            "Test_001": {
                "postcode": "BB7 2AG",
                "house_number": "5",
                "street": "Pimlico Road",
            },
            "Test_002": {
                "postcode": "PR3 3EA",
                "house_number": "28",
                "street": "Towneley Road",
            },
        },
    )
    requires = frozenset({"postcode"})
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        response = await http.get(
            SEARCH_URL,
            params={
                "directoryID": "1",
                "keywords": postcode,
                "search": "Search directory",
            },
            timeout=30,
        )
        records = [
            (anchor.get_text(strip=True), anchor["href"])
            for anchor in soup(response.text).select("a.list__link[href]")
            if anchor["href"].startswith("/directory-record/")
        ]
        if not records:
            raise AddressNotFound(f"No Ribble Valley addresses found for {postcode}")

        match = match_address(address, records, text=lambda record: record[0])
        record_response = await http.get(BASE + match[1], timeout=30)
        record_page = soup(record_response.text)
        link = next(
            (
                anchor["href"]
                for anchor in record_page.select("dd a[href]")
                if "/downloads/file/" in anchor["href"]
            ),
            None,
        )
        if not link:
            raise UpstreamError("No bin calendar link on address record")

        pdf_response = await http.get(link, timeout=30)
        try:
            collections = await asyncio.to_thread(_parse_calendar, pdf_response.content)
        except ValueError as exc:
            raise UpstreamError(f"Could not read Ribble Valley calendar: {exc}") from exc

        today = datetime.now().date()
        upcoming = [collection for collection in collections if collection.date >= today]
        if not upcoming:
            raise UpstreamError("No upcoming collections found in calendar PDF")
        return upcoming


SCRAPER = RibbleValley()
