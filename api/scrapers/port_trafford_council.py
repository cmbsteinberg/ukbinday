"""Trafford Council bin collections (apps.trafford.gov.uk + published calendar PDF).

Lookup chain:
1. POST postcode to https://apps.trafford.gov.uk/bincollections/ -> HTML with an
   address <select> (option value = UPRN) and an inline
   ``collectionData = JSON.parse("[...]")`` blob holding, per UPRN, the
   collection weekday and a ``CalendarLink`` to the property's A/B calendar PDF
   (e.g. ``.../2025-11/Wed-CAL-B.pdf``).
2. GET that PDF (www.trafford.gov.uk is behind CloudFront and returns 403 to
   plain httpx, so curl_cffi Chrome impersonation is used) and read the dated
   table with pdfplumber. Each date in the table is preceded by a vector
   symbol identifying the bin: grey circle = grey bin (waste we cannot
   recycle), black triangle = black bin (mixed recycling), blue plus = blue bin
   (paper and card). The symbol is identified by its CMYK fill colour.

No dates are computed or invented: every date returned is a date printed in the
council's own calendar for that weekday + week (A/B) combination, so there is
no stale week anchor to maintain. Only dates from today onwards are returned.
The weekly green food-waste caddy is described in the PDF but has no per-date
entries and is not emitted. The calendar covers one financial year; once the
council publishes the next PDF the live page link changes automatically.

Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

import io
import json
import logging
import re
from datetime import date

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from api.compat.curl_cffi_fallback import AsyncClient as _CurlClient
from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentNotFound

TITLE = "Trafford Council"
DESCRIPTION = "Source for trafford.gov.uk bin collections (postcode lookup + council-published A/B calendar PDF)."
URL = "https://www.trafford.gov.uk"
TEST_CASES = {
    "33 Tatton Road, Sale M33 7EE": {"uprn": "100011699343", "postcode": "M33 7EE"},
    "35 Tatton Road, Sale M33 7EE": {"uprn": "100011699344", "postcode": "M33 7EE"},
}

_LOGGER = logging.getLogger(__name__)

_SEARCH_URL = "https://apps.trafford.gov.uk/bincollections/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ICON_MAP = {
    "Grey bin": Icons.GENERAL_WASTE,
    "Black bin": Icons.RECYCLING,
    "Blue bin": Icons.PAPER,
}

PARAM_DESCRIPTIONS = {
    "en": {
        "uprn": "UPRN of the property (the value of the address option on the Trafford bin lookup)",
        "postcode": "Postcode of the property (e.g. M33 7EE)",
    }
}

HOW_TO_GET_ARGUMENTS_DESCRIPTION = {
    "en": "Find your UPRN at https://www.findmyaddress.co.uk/ and supply your postcode.",
}

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December",
        ],
        1,
    )
}  # fmt: skip


def _classify(obj: dict) -> str | None:
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
    page = pdfplumber.open(io.BytesIO(data)).pages[0]
    words = page.extract_words()
    shapes = [o for o in page.curves + page.rects if o.get("fill") and o["width"] < 15]
    out: list[tuple[date, str]] = []
    for mw in words:
        if mw["text"] not in _MONTHS or mw["x0"] > 60:
            continue
        row = [w for w in words if abs(w["top"] - mw["top"]) < 4 and w["x0"] > mw["x0"]]
        year = next((int(w["text"]) for w in row if re.fullmatch(r"20\d\d", w["text"])), None)
        if year is None:
            continue
        for w in row:
            if not re.fullmatch(r"\d{1,2}", w["text"]) or w["x0"] < 130:
                continue
            mid = (w["top"] + w["bottom"]) / 2
            near = [
                s
                for s in shapes
                if abs((s["top"] + s["bottom"]) / 2 - mid) < 6 and 0 < w["x0"] - s["x1"] < 14
            ]
            if not near:
                continue
            kind = _classify(near[0])
            if kind is None:
                continue
            try:
                out.append((date(year, _MONTHS[mw["text"]], int(w["text"])), kind))
            except ValueError:
                continue
    return out


class Source:
    def __init__(self, uprn: str | int, postcode: str):
        if not uprn or not postcode:
            raise SourceArgumentNotFound("uprn", "uprn and postcode are required")
        self._uprn = str(uprn).strip().lstrip("0")
        self._postcode = str(postcode).strip().upper()

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT}, follow_redirects=True, timeout=30
        ) as client:
            r = await client.post(_SEARCH_URL, data={"Postcode": self._postcode})
            r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        if not any(
            o.get("value", "").lstrip("0") == self._uprn for o in soup.select("#SelectedAddress option")
        ):
            raise ValueError(f"UPRN {self._uprn} not found for postcode {self._postcode}")

        m = re.search(r"collectionData\s*=\s*JSON\.parse\((['\"])(.*?)\1\);", r.text, re.S)
        if not m:
            raise ValueError("Trafford collection data not found in page")
        raw = m.group(2)
        raw = json.loads(f'"{raw}"') if m.group(1) == '"' else raw
        entries = json.loads(raw)
        entry = next((e for e in entries if str(e.get("Id", "")).lstrip("0") == self._uprn), None)
        if not entry:
            raise ValueError(f"No collection data for UPRN {self._uprn}")

        link = next(
            (c.get("CalendarLink") for c in entry.get("Collections", []) if c.get("CalendarLink")),
            None,
        )
        if not link:
            raise ValueError("No calendar link for this address")

        async with _CurlClient(timeout=60) as client:
            pdf = await client.get(link)
            pdf.raise_for_status()

        today = date.today()
        seen = set()
        result: list[Collection] = []
        for d, kind in sorted(_parse_pdf(pdf.content)):
            if d < today or (d, kind) in seen:
                continue
            seen.add((d, kind))
            result.append(Collection(date=d, t=kind, icon=ICON_MAP.get(kind)))
        if not result:
            raise ValueError("No upcoming collections found in Trafford calendar")
        return result
