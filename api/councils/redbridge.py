"""Redbridge: fetches a UPRN-specific collection calendar PDF and parses its schedule."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from io import BytesIO

from pypdf import PdfReader

from api.councils._base import Address, Collection, Http, Meta, Scraper

MONTH_REGEX = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$",
    re.I,
)
_WEEKDAY_HEADER_REGEX = re.compile(r"^(Sun\s+Mon\s+Tue\s+Wed\s+Thu\s+Fri\s+Sat)$", re.I)
_DAY_GROUP_REGEX = re.compile(r"^(?:\d{1,2})(?:\s+\d{1,2})*$")
_KNOWN_SERVICES = {"REFUSE", "RECYCLING", "GARDEN", "FOOD"}


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text


def _extract_collections_from_text(text: str) -> list[Collection]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    current_month_name: str | None = None
    current_year: int | None = None
    entries: list[Collection] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        month_match = MONTH_REGEX.match(line)
        if month_match:
            current_month_name = month_match.group(1)
            current_year = int(month_match.group(2))
            i += 1
            continue

        lower = line.lower()
        if (
            _WEEKDAY_HEADER_REGEX.match(line)
            or lower.startswith("london borough of redbridge")
            or "your collection schedule" in lower
        ):
            i += 1
            continue

        if current_month_name and current_year and _DAY_GROUP_REGEX.match(line):
            days: list[int] = []
            for token in line.split():
                try:
                    day = int(token)
                    if 1 <= day <= 31:
                        days.append(day)
                except ValueError:
                    pass

            services: list[str] = []
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                lower_next = next_line.lower()
                if (
                    MONTH_REGEX.match(next_line)
                    or _WEEKDAY_HEADER_REGEX.match(next_line)
                    or _DAY_GROUP_REGEX.match(next_line)
                    or "your collection schedule" in lower_next
                ):
                    break

                service = next_line.strip()
                if service.split(" ")[0].upper() in _KNOWN_SERVICES:
                    services.append(service)
                j += 1

            if days and services:
                month = datetime.strptime(current_month_name, "%B").month
                collection_date = datetime(current_year, month, max(days)).date()
                for service in services:
                    entries.append(Collection(date=collection_date, type=service))

            i = j
            continue

        i += 1

    return entries


class Redbridge(Scraper):
    meta = Meta(
        title="Redbridge Council",
        url="https://redbridge.gov.uk",
        lads=("E09000026",),
        cases={
            "council office recycling only": {"uprn": "10034922090"},
            "refuse and recycling only": {"uprn": "10013585215"},
            "a church vicarage, garden, recycling, refuse": {"uprn": "10034912354"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(
            "https://my.redbridge.gov.uk/RecycleRefuse/GetFile",
            params={"uprn": address.need("uprn")},
        )
        pdf_text = await asyncio.to_thread(_extract_text_from_pdf, response.content)
        return _extract_collections_from_text(pdf_text)


SCRAPER = Redbridge()
