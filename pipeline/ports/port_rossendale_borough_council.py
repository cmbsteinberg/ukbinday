"""Rossendale Borough Council bin collections (Jadu directory + zone PDF).

Flow (plain HTTP, no browser):
  1. GET https://www.rossendale.gov.uk/directory/search?directoryID=10094&keywords=<postcode>
     (Jadu directory "Bin Collection Days") -> list of address records.
  2. Pick the record whose address string contains the supplied `address`
     (a single-result postcode needs no address). GET the record page; its
     "Link" field is the PDF for that address's collection zone (e.g. Zone 4A).
     NB the URL slug says "2023-24" but the file is refreshed in place and
     currently covers April 2026 - March 2027.
  3. Parse the PDF text with pdfplumber. Each row reads
     "MONTH YY d d d  MONTH YY d d d": left block = General Waste, right block
     = Recycling. The dates are printed explicitly (bank-holiday shifts
     included), so nothing is calculated here.

Not emitted: food waste caddy (weekly on the normal collection day, no dates
printed) and garden waste (per-household sticker).

Requires pdfplumber (already installed in the environment).

Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

import io
import re
from datetime import date
from urllib.parse import urljoin

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]

TITLE = "Rossendale Borough Council"
DESCRIPTION = "Source for rossendale.gov.uk bin collections."
URL = "https://www.rossendale.gov.uk/directory/10094/bin-collection-days"
TEST_CASES = {
    "Test_001": {"postcode": "BB4 5AA", "address": "13 Spring Lane"},
    "Test_002": {"postcode": "BB4 6AA", "address": "Flat 2, 14 Bury Road"},
    "Test_003": {"postcode": "OL13 0AA", "address": "9a Union Street"},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
}
BASE = "https://www.rossendale.gov.uk"
SEARCH_URL = f"{BASE}/directory/search"

MONTHS = [
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
    "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
]  # fmt: skip
_BLOCK = re.compile(r"(" + "|".join(MONTHS) + r")\s+(\d{2})((?:\s+\d{1,2})+)(?!\d)")

BINS = [
    ("General Waste", Icons.GENERAL_WASTE),
    ("Recycling", Icons.RECYCLING),
]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _parse_pdf_text(text: str) -> list[tuple[str, date]]:
    out: list[tuple[str, date]] = []
    for line in text.splitlines():
        blocks = _BLOCK.findall(line)
        if len(blocks) != 2:
            continue
        for (month, yy, days), (bin_type, _) in zip(blocks, BINS):
            m = MONTHS.index(month) + 1
            for d in days.split():
                out.append((bin_type, date(2000 + int(yy), m, int(d))))
    return out


class Source:
    def __init__(self, postcode: str, address: str | None = None):
        self._postcode = postcode.strip().upper()
        self._address = address

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(
            follow_redirects=True, headers=HEADERS, timeout=30
        ) as client:
            r = await client.get(
                SEARCH_URL,
                params={
                    "directoryID": "10094",
                    "search": "Search",
                    "keywords": self._postcode,
                },
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            records = [
                (a.get_text(" ", strip=True), a["href"])
                for a in soup.select("a.list__link")
                if "/directory-record/" in a.get("href", "")
            ]
            if not records:
                raise ValueError(f"No addresses found for postcode {self._postcode}")

            if self._address:
                want = _norm(self._address)
                # Strip the postcode / town from the listed string before comparing.
                hits = [rec for rec in records if want in _norm(rec[0])]
                exact = [
                    rec
                    for rec in hits
                    if _norm(rec[0]).startswith(want)
                ]
                hits = exact or hits
            else:
                hits = records
            if not hits:
                raise ValueError(
                    f"Address {self._address!r} not found; options: "
                    + "; ".join(t for t, _ in records)
                )
            if len(hits) > 1 and not self._address:
                raise ValueError(
                    "Multiple addresses for postcode, pass address: "
                    + "; ".join(t for t, _ in records)
                )

            rec = await client.get(urljoin(BASE, hits[0][1]))
            rec.raise_for_status()
            rsoup = BeautifulSoup(rec.text, "html.parser")
            link = next(
                (
                    a["href"]
                    for a in rsoup.select("dd.definition__content--link a[href]")
                ),
                None,
            )
            if not link:
                raise ValueError("No calendar link on address record")

            pdf = await client.get(urljoin(BASE, link))
            pdf.raise_for_status()

        with pdfplumber.open(io.BytesIO(pdf.content)) as doc:
            text = "\n".join(p.extract_text() or "" for p in doc.pages)
        parsed = _parse_pdf_text(text)
        if not parsed:
            raise ValueError("Could not parse any dates from zone calendar PDF")

        today = date.today()
        icons = dict(BINS)
        return [
            Collection(date=d, t=t, icon=icons[t])
            for t, d in sorted(parsed, key=lambda x: x[1])
            if d >= today
        ]
