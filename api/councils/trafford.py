"""Trafford: postcode search finds the UPRN's published A/B calendar PDF, parsed for upcoming collections."""

from __future__ import annotations

import asyncio
import io
import json
import re
from datetime import date
from typing import Any

import pdfplumber

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    soup,
)

_SEARCH_URL = "https://apps.trafford.gov.uk/bincollections/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_MONTHS = {
    month: number
    for number, month in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        1,
    )
}


def _classify(obj: dict[str, Any]) -> str | None:
    """Map a symbol's CMYK fill colour to a bin name."""
    col = obj.get("non_stroking_color")
    if not col or len(col) != 4:
        return None
    c, _m, _y, k = col
    if c > 0.6 and k < 0.2:
        return "Blue bin"
    if k > 0.4:
        return "Black bin"
    return "Grey bin"


def _parse_pdf(data: bytes) -> list[tuple[date, str]]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        shapes = [obj for obj in page.curves + page.rects if obj.get("fill") and obj["width"] < 15]

    out: list[tuple[date, str]] = []
    for month_word in words:
        if month_word["text"] not in _MONTHS or month_word["x0"] > 60:
            continue
        row = [
            word
            for word in words
            if abs(word["top"] - month_word["top"]) < 4 and word["x0"] > month_word["x0"]
        ]
        year = next(
            (int(word["text"]) for word in row if re.fullmatch(r"20\d\d", word["text"])),
            None,
        )
        if year is None:
            continue
        for word in row:
            if not re.fullmatch(r"\d{1,2}", word["text"]) or word["x0"] < 130:
                continue
            mid = (word["top"] + word["bottom"]) / 2
            near = [
                shape
                for shape in shapes
                if abs((shape["top"] + shape["bottom"]) / 2 - mid) < 6
                and 0 < word["x0"] - shape["x1"] < 14
            ]
            if not near:
                continue
            kind = _classify(near[0])
            if kind is None:
                continue
            try:
                out.append((date(year, _MONTHS[month_word["text"]], int(word["text"])), kind))
            except ValueError:
                continue
    return out


class Trafford(Scraper):
    meta = Meta(
        title="Trafford Council",
        url="https://www.trafford.gov.uk",
        lads=("E08000009",),
        cases={
            "33 Tatton Road": {"uprn": "100011699343", "postcode": "M33 7EE"},
            "35 Tatton Road": {"uprn": "100011699344", "postcode": "M33 7EE"},
        },
    )
    requires = frozenset({"uprn", "postcode"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").lstrip("0")
        postcode = address.need("postcode").strip().upper()

        response = await http.post(
            _SEARCH_URL,
            data={"Postcode": postcode},
            headers={"User-Agent": _USER_AGENT},
            timeout=30,
        )
        page = soup(response.text)
        if not any(
            option.get("value", "").lstrip("0") == uprn
            for option in page.select("#SelectedAddress option")
        ):
            raise AddressNotFound(f"UPRN {uprn} not found for postcode {postcode}")

        match = re.search(r"collectionData\s*=\s*JSON\.parse\((['\"])(.*?)\1\);", response.text, re.S)
        if not match:
            raise UpstreamError("Trafford collection data not found in page")
        raw = match.group(2)
        try:
            raw = json.loads(f'"{raw}"') if match.group(1) == '"' else raw
            entries = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UpstreamError("Trafford collection data is invalid") from exc

        entry = next(
            (item for item in entries if str(item.get("Id", "")).lstrip("0") == uprn),
            None,
        )
        if not entry:
            raise AddressNotFound(f"No collection data for UPRN {uprn}")

        link = next(
            (
                collection.get("CalendarLink")
                for collection in entry.get("Collections", [])
                if collection.get("CalendarLink")
            ),
            None,
        )
        if not link:
            raise InputError("No calendar link for this address")

        pdf = await http.get(link, timeout=60)
        dates = await asyncio.to_thread(_parse_pdf, pdf.content)
        today = date.today()
        collections = [
            Collection(collection_date, kind)
            for collection_date, kind in dates
            if collection_date >= today
        ]
        if not collections:
            raise InputError("No upcoming collections found in Trafford calendar")
        return collections


SCRAPER = Trafford()
