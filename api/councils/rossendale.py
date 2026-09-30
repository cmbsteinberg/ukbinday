"""Rossendale: search the Jadu directory by postcode, then parse the address's zone PDF."""

from __future__ import annotations

import asyncio
import io
import re
from datetime import date
from urllib.parse import urljoin

import pdfplumber

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
)

_BASE = "https://www.rossendale.gov.uk"
_SEARCH_URL = f"{_BASE}/directory/search"
_MONTHS = (
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
)
_BLOCK = re.compile(
    r"(" + "|".join(_MONTHS) + r")\s+(\d{2})((?:\s+\d{1,2})+)(?!\d)"
)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _parse_pdf_text(text: str) -> list[tuple[str, date]]:
    parsed: list[tuple[str, date]] = []
    for line in text.splitlines():
        blocks = _BLOCK.findall(line)
        if len(blocks) != 2:
            continue
        for (month, year, days), bin_type in zip(blocks, ("General Waste", "Recycling"), strict=False):
            month_number = _MONTHS.index(month) + 1
            for day in days.split():
                parsed.append((bin_type, date(2000 + int(year), month_number, int(day))))
    return parsed


def _extract_pdf_text(content: bytes) -> str:
    with pdfplumber.open(io.BytesIO(content)) as document:
        return "\n".join(page.extract_text() or "" for page in document.pages)


class Rossendale(Scraper):
    meta = Meta(
        title="Rossendale Borough Council",
        url="https://www.rossendale.gov.uk/directory/10094/bin-collection-days",
        lads=("E07000125",),
        cases={
            "Test_001": {"postcode": "BB4 5AA", "house_number": "13", "street": "Spring Lane"},
            "Test_002": {"postcode": "BB4 6AA", "house_number": "Flat 2", "street": "14 Bury Road"},
            "Test_003": {"postcode": "OL13 0AA", "house_number": "9a", "street": "Union Street"},
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
            _SEARCH_URL,
            params={
                "directoryID": "10094",
                "search": "Search",
                "keywords": postcode,
            },
            timeout=30,
        )
        records = [
            (link.get_text(" ", strip=True), link["href"])
            for link in soup(response.text).select("a.list__link")
            if "/directory-record/" in link.get("href", "")
        ]
        if not records:
            raise AddressNotFound(f"No addresses found for postcode {postcode}")

        if address.first_line:
            try:
                selected = match_address(address, records, text=lambda record: record[0])
            except AddressNotFound:
                selected = None
                if address.house_number and address.street:
                    glued = re.compile(rf"^{re.escape(address.house_number)}(?=[A-Za-z]{{2}})", re.I)
                    street = _norm(address.street)
                    selected = next(
                        (
                            record
                            for record in records
                            if glued.match(record[0]) and street in _norm(record[0])
                        ),
                        None,
                    )
                if selected is None:
                    raise
        elif len(records) == 1:
            selected = records[0]
        else:
            raise InputError(
                "Multiple addresses for postcode, pass an address: "
                + "; ".join(label for label, _ in records)
            )

        record_response = await http.get(urljoin(_BASE, selected[1]), timeout=30)
        record_page = soup(record_response.text)
        link = next(
            (
                anchor["href"]
                for anchor in record_page.select("dd.definition__content--link a[href]")
            ),
            None,
        )
        if not link:
            raise UpstreamError("No calendar link on address record")

        pdf_response = await http.get(urljoin(_BASE, link), timeout=30)
        text = await asyncio.to_thread(_extract_pdf_text, pdf_response.content)
        parsed = _parse_pdf_text(text)
        if not parsed:
            raise UpstreamError("Could not parse any dates from zone calendar PDF")

        today = date.today()
        return [
            Collection(day, bin_type)
            for bin_type, day in parsed
            if day >= today
        ]


SCRAPER = Rossendale()
