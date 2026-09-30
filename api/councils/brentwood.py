"""Brentwood: look up a property's route in GeoServer, then read collection dates from its route calendar PDF."""

from __future__ import annotations

import asyncio
import io
import re
from datetime import date, timedelta

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
)

_WFS_URL = "https://maps.brentwood.gov.uk/geoserver/ows"
_LAYER = "geodata:Recycling and Waste"
_MEDIA_RE = re.compile(r"^https://www\.brentwood\.gov\.uk/media/\d+$")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_MONTHS = {
    month: index
    for index, month in enumerate(
        (
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
        ),
        start=1,
    )
}
_WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


def _parse_calendar(pdf_bytes: bytes) -> tuple[int, list[tuple[date, bool]]]:
    """Return the route weekday and its [(date, is_blue_week)] calendar entries."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        boxes = [
            rect
            for rect in page.rects
            if 15 < rect["x1"] - rect["x0"] < 25
            and 15 < rect["bottom"] - rect["top"] < 25
        ]

    weekday = None
    for word in words:
        if word["text"].upper() in _WEEKDAYS and word["top"] < 160:
            weekday = _WEEKDAYS.index(word["text"].upper())
            break
    if weekday is None:
        raise ValueError("route weekday not found in calendar PDF")

    headers = []
    for index, word in enumerate(words[:-1]):
        next_word = words[index + 1]
        if (
            word["text"].upper() in _MONTHS
            and re.fullmatch(r"20\d\d", next_word["text"])
            and abs(next_word["top"] - word["top"]) < 3
        ):
            headers.append(
                (
                    word["x0"],
                    word["top"],
                    _MONTHS[word["text"].upper()],
                    int(next_word["text"]),
                )
            )

    entries: list[tuple[date, bool]] = []
    for x0, top, month, year in headers:
        for word in words:
            if not re.fullmatch(r"\d{1,2}", word["text"]):
                continue
            if not (top + 10 < word["top"] < top + 45 and x0 - 10 <= word["x0"] < x0 + 190):
                continue
            center_x = (word["x0"] + word["x1"]) / 2
            center_y = (word["top"] + word["bottom"]) / 2
            box = next(
                (
                    rect
                    for rect in boxes
                    if rect["x0"] <= center_x <= rect["x1"]
                    and rect["top"] <= center_y <= rect["bottom"]
                ),
                None,
            )
            if box is None:
                continue
            try:
                day = date(year, month, int(word["text"]))
            except ValueError:
                continue
            if day.weekday() != weekday:
                for offset in (-1, 1, -2, 2, -3, 3):
                    candidate = day + timedelta(days=offset)
                    if candidate.weekday() == weekday:
                        day = candidate
                        break
                else:
                    continue
            entries.append((day, bool(box["fill"])))

    return weekday, sorted(set(entries))


class Brentwood(Scraper):
    meta = Meta(
        title="Brentwood Borough Council",
        url="https://www.brentwood.gov.uk/collection-day",
        lads=("E07000068",),
        cases={
            "127 Greenshaw, Brentwood CM14 4YP": {"uprn": "100090336817"},
            "Route 1 (Monday)": {"uprn": "10093276507"},
            "Route 8 (Friday)": {"uprn": "10093274131"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        if not uprn.isdigit():
            raise InputError("UPRN must be numeric")

        response = await http.get(
            _WFS_URL,
            params={
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeNames": _LAYER,
                "outputFormat": "application/json",
                "CQL_FILTER": f"uprn='{uprn}'",
                "propertyName": "uprn,garden_round,glass_round,calendar,address",
            },
            timeout=60,
        )
        features = response.json().get("features", [])
        if not features:
            raise AddressNotFound(f"UPRN {uprn} not found in Brentwood collection layer")

        properties = features[0]["properties"]
        calendar_url = properties.get("calendar") or ""
        if not _MEDIA_RE.match(calendar_url):
            raise InputError(
                "Property has no published collection calendar "
                "(non-household or unassigned round)"
            )

        pdf_response = await http.get(calendar_url, timeout=60)

        try:
            _weekday, dates = await asyncio.to_thread(_parse_calendar, pdf_response.content)
        except ValueError as exc:
            raise UpstreamError(f"Could not parse Brentwood calendar PDF: {exc}") from exc
        if not dates:
            raise UpstreamError("No dates parsed from Brentwood calendar PDF")

        garden = properties.get("garden_round") == "GW"
        glass = properties.get("glass_round") == "GL"
        today = date.today()
        collections: list[Collection] = []
        for day, blue in dates:
            if day < today:
                continue
            collections.append(Collection(day, "Refuse"))
            collections.append(Collection(day, "Food Waste"))
            if blue:
                collections.append(Collection(day, "Paper and Card (Blue Sack)"))
                if glass:
                    collections.append(Collection(day, "Glass"))
                if garden:
                    collections.append(Collection(day, "Garden Waste"))
            else:
                collections.append(Collection(day, "Plastic and Cans (White Sack)"))
        return collections


SCRAPER = Brentwood()
