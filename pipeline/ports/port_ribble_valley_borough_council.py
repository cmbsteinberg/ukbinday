"""Ribble Valley Borough Council bin collections (Jadu directory + PDF calendar).

Flow (plain HTTP, no browser):
  1. GET /directory/search?directoryID=1&keywords=<postcode> — the "Find your
     bin collection day" Jadu directory. Each record is one address, titled
     like "5 PIMLICO ROAD CLITHEROE LANCASHIRE BB7 2AG". There is no UPRN in
     the directory, so the address is matched by text (house number/name).
  2. GET the matching /directory-record/<id>/... page: it publishes the
     collection weekday, the white-sack week colour, and a link to the
     council's annual PDF calendar (e.g. /downloads/file/2583/tuesday-collection-green).
  3. The PDF (one page, "April 2026 - March 2027") lists every collection
     date per month. Each date sits on a colour-filled cell: green cell =
     garden (green) bin week, blue cell = recycling (blue) bin week; a
     "P" on the cell marks a paper/card (white sack) week. The burgundy
     general-waste bin is collected every listed date. Dates are read from
     the published calendar with pdfplumber (already a dependency) — nothing
     is projected or invented.

Caveats: the PDF notes that December dates may change ("confirmed nearer the
time"), so Christmas-period dates can move. The calendar covers one
financial year only. Bank holidays are collected as normal except at
Christmas/New Year.

Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

import io
import logging
import re
from datetime import date, datetime
from html import unescape

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]

TITLE = "Ribble Valley Borough Council"
DESCRIPTION = "Source for ribblevalley.gov.uk bin collections."
URL = "https://www.ribblevalley.gov.uk/directory/1/find-your-bin-collection-day"
TEST_CASES = {
    "Test_001": {"postcode": "BB7 2AG", "address": "5 Pimlico Road"},
    "Test_002": {"postcode": "PR3 3EA", "address": "28 Towneley Road"},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
}

_LOGGER = logging.getLogger(__name__)

BASE = "https://www.ribblevalley.gov.uk"
SEARCH_URL = BASE + "/directory/search"

MONTHS = [
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
    "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
]  # fmt: skip



def _bin_colour(cmyk) -> str | None:
    """Classify a CMYK cell fill as 'green' or 'blue'.

    The PDFs use a different palette per weekday file (Tuesday: green
    (0.75,0.05,1,0) / blue (0.5,0.45,0.05,0); Monday: green (0.56,0.04,0.75,0)
    / blue (1,0.9,0.1,0)), so match on hue: green cells carry high yellow,
    blue cells carry low yellow.
    """
    if not cmyk or len(cmyk) != 4:
        return None
    return "green" if cmyk[2] > 0.5 else "blue"


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", unescape(s).upper()).split())


def parse_calendar(pdf_bytes: bytes) -> list[Collection]:
    """Extract dated collections from a Ribble Valley calendar PDF."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        rects = [
            r
            for r in page.rects
            if r.get("fill") and 19 <= r["width"] <= 22 and abs(r["height"] - 19) < 2
        ]

    text = " ".join(w["text"] for w in words)
    m = re.search(r"([A-Za-z]+)\s+(\d{4})\s*-\s*([A-Za-z]+)\s+(\d{4})", text)
    if not m:
        raise ValueError("Could not read calendar year range from PDF")
    start_year = int(m.group(2))

    headers = [w for w in words if w["text"] in MONTHS]
    papers = [w for w in words if w["text"] == "P"]
    dates = [w for w in words if re.fullmatch(r"\d{1,2}", w["text"])]

    out: list[Collection] = []
    for d in dates:
        # Month header: same band (8-20pt above), nearest to the left.
        cands = [
            h
            for h in headers
            if 8 <= d["top"] - h["top"] <= 20 and h["x0"] <= d["x0"] + 3
        ]
        if not cands:
            continue
        hdr = max(cands, key=lambda h: h["x0"])
        month = MONTHS.index(hdr["text"]) + 1
        year = start_year if month >= 4 else start_year + 1
        try:
            day = date(year, month, int(d["text"]))
        except ValueError:
            continue

        cx = (d["x0"] + d["x1"]) / 2
        rect = next(
            (r for r in rects if r["x0"] - 1 <= cx <= r["x1"] + 1 and 3 <= r["top"] - d["top"] <= 15),
            None,
        )
        out.append(Collection(date=day, t="Burgundy bin (general waste)", icon=Icons.GENERAL_WASTE))
        if rect is None:
            continue
        colour = rect.get("non_stroking_color")
        kind = _bin_colour(colour)
        if kind == "green":
            out.append(Collection(date=day, t="Green bin (garden waste)", icon=Icons.GARDEN))
        elif kind == "blue":
            out.append(Collection(date=day, t="Blue bin (recycling)", icon=Icons.RECYCLING))
        has_paper = any(
            rect["x0"] <= (p["x0"] + p["x1"]) / 2 <= rect["x1"]
            and rect["top"] <= p["top"] <= rect["bottom"]
            for p in papers
        )
        if has_paper:
            out.append(Collection(date=day, t="Paper and card (white sack)", icon=Icons.PAPER))
    return sorted(out, key=lambda c: (c.date, c.type))


class Source:
    def __init__(self, postcode: str, address: str):
        self._postcode = postcode.strip().upper()
        self._address = address.strip()

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=30) as s:
            r = await s.get(
                SEARCH_URL,
                params={"directoryID": "1", "keywords": self._postcode, "search": "Search directory"},
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            records = [
                (a.get_text(strip=True), a["href"])
                for a in soup.select("a.list__link")
                if a["href"].startswith("/directory-record/")
            ]
            if not records:
                raise ValueError(f"No Ribble Valley addresses found for {self._postcode}")

            want = _norm(self._address)
            match = None
            for title, href in records:
                t = _norm(title)
                if t == want or t.startswith(want + " "):
                    match = href
                    break
            if match is None:
                raise ValueError(
                    f"Address {self._address!r} not found for {self._postcode}; "
                    f"candidates: {[t for t, _ in records][:10]}"
                )

            r2 = await s.get(BASE + match)
            r2.raise_for_status()
            rec = BeautifulSoup(r2.text, "html.parser")
            link = next(
                (a["href"] for a in rec.select("dd a[href]") if "/downloads/file/" in a["href"]),
                None,
            )
            if not link:
                raise ValueError("No bin calendar link on address record")
            r3 = await s.get(link)
            r3.raise_for_status()

        today = datetime.now().date()
        entries = [c for c in parse_calendar(r3.content) if c.date >= today]
        if not entries:
            raise ValueError("No upcoming collections found in calendar PDF")
        return entries
