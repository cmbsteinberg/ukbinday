"""Newry, Mourne and Down District Council bin collections (postcode -> zone PDF).

Flow (plain HTTP, no browser):
  1. POST https://www.newrymournedown.org/weekly-bin-collection-and-calendar
     with PostcodeBT (outward code, e.g. BT34), PostcodeEND (last three
     characters, e.g. 2AP), postback=1. The page lists every address on the
     postcode with a "View Schedule" link to a zone PDF such as
     /bin-collections/TUE-Z1.pdf (day-of-week prefix + zone code).
  2. Download that PDF. It is a one-page "Recycling Collection Calendar
     2026-2027" leaflet: one row per month (April..April), one coloured box per
     collection date. The digits are vector outlines, not text, so the box
     positions/colours are what can be read:
       - one wide box (blue or black)    -> that bin only
       - two half-width boxes (e.g. black + brown, or blue + brown, as drawn
         two-tone on the leaflet)        -> both bins
     Every box is a collection on the zone's weekday (from the PDF file name),
     in date order within its month. The month row order and the weekday give
     the dates. Each row's box count is checked against the number of that
     weekday in the month (the final April row may stop early), and the start year is taken from the PDF title
     ("2026-2027"); any mismatch raises rather than guessing.
  3. Boxes with a green border (public holiday, normal collection) are kept.
     Red-bordered boxes ("alternative collection") move to a different day
     whose digits cannot be read, so they are skipped with a warning.

Needs pdfplumber (present in the project environment).

Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

import calendar
import io
import logging
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Newry, Mourne and Down District Council"
DESCRIPTION = "Source for newrymournedown.org bin collections."
URL = "https://www.newrymournedown.org/weekly-bin-collection-and-calendar"
TEST_CASES = {
    "1 John Mitchel Street, Newry (Fri Z-V2)": {
        "postcode": "BT34 2AP",
        "address": "1 John Mitchel Street",
    },
    "9 Kildare Street, Newry (Tue Z1)": {
        "postcode": "BT34 1DQ",
        "address": "9 Kildare Street",
    },
    "44 Glenmore Road, Belleek (Tue Z1)": {
        "postcode": "BT35 7PU",
        "address": "44 Glenmore Road",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
}

_LOGGER = logging.getLogger(__name__)

WEEKDAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
BLUE = (0.098, 0.4627, 0.8235)
BLACK = (0.0, 0.0, 0.0)
BROWN = (0.4745, 0.3333, 0.2824)
KIND_TYPE = {"blue": "Blue Bin", "black": "Black Bin", "brown": "Brown Bin"}

ICON_MAP = {
    "Blue Bin": "mdi:recycle",
    "Black Bin": "mdi:trash-can",
    "Brown Bin": "mdi:food-apple",
}


def _close(a, b) -> bool:
    return (
        a is not None
        and len(a) == len(b)
        and all(abs(x - y) < 0.01 for x, y in zip(a, b))
    )


def _is_red(col) -> bool:
    return (
        isinstance(col, (tuple, list))
        and len(col) == 3
        and col[0] > 0.8
        and col[1] < 0.3
        and col[2] < 0.3
    )


def _parse_pdf(content: bytes, weekday: int) -> list[Collection]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page = pdf.pages[0]
        title = "".join(c["text"] for c in page.chars)
        # Title text is rendered with doubled glyphs ("22002266--22002277").
        m = re.search(r"(20\d\d)-(20\d\d)", re.sub(r"(.)\1", r"\1", title))
        if not m or int(m.group(2)) != int(m.group(1)) + 1:
            raise ValueError("Could not read calendar year range from PDF title")
        start_year = int(m.group(1))

        boxes = []
        for r in page.rects:
            if not r.get("fill"):
                continue
            col = r["non_stroking_color"]
            if _close(col, BLUE):
                kind = "blue"
            elif _close(col, BLACK):
                kind = "black"
            elif _close(col, BROWN):
                kind = "brown"
            else:
                continue
            if not (120 < r["top"] < 450 and r["height"] < 20):
                continue
            boxes.append((round(r["top"]), r["x0"], kind, r))
        # Cell borders are separate stroked curves, one per date cell.
        borders = [
            (c["x0"], c["top"], c["stroking_color"])
            for c in page.curves
            if c.get("stroke") and c["width"] > 40 and 120 < c["top"] < 450
        ]

    def border_of(rect):
        for bx, by, col in borders:
            if abs(bx - rect["x0"]) < 4 and abs(by - rect["top"]) < 4:
                return col
        return None

    rows: dict[int, list] = {}
    for top, x0, kind, r in boxes:
        # Merge rows whose tops differ by sub-point rounding.
        key = next((k for k in rows if abs(k - top) <= 3), top)
        rows.setdefault(key, []).append((x0, kind, r))
    ordered = [sorted(v, key=lambda t: t[0]) for _, v in sorted(rows.items())]
    if len(ordered) != 13:
        raise ValueError(f"Expected 13 month rows in PDF, found {len(ordered)}")

    out: list[Collection] = []
    for idx, row in enumerate(ordered):
        month = (3 + idx) % 12 + 1
        year = start_year + (3 + idx) // 12
        cells = []  # (types, border)
        i = 0
        while i < len(row):
            _, kind, r = row[i]
            if r["width"] > 35:  # one wide box: a single bin
                cells.append(([KIND_TYPE[kind]], border_of(r)))
                i += 1
            elif i + 1 < len(row) and row[i + 1][2]["width"] < 35:
                # two half-width boxes: two-tone date, both bins collected
                cells.append(
                    ([KIND_TYPE[kind], KIND_TYPE[row[i + 1][1]]], border_of(r))
                )
                i += 2
            else:
                raise ValueError(
                    f"Unexpected box layout in {year}-{month:02d} row: "
                    f"{[(round(x), k) for x, k, _ in row]}"
                )

        days = [
            d
            for d in range(1, calendar.monthrange(year, month)[1] + 1)
            if date(year, month, d).weekday() == weekday
        ]
        if idx == len(ordered) - 1 and len(cells) <= len(days):
            # The leaflet stops part-way through the final April.
            days = days[: len(cells)]
        if len(days) != len(cells):
            raise ValueError(
                f"{year}-{month:02d}: {len(cells)} boxes but {len(days)} matching weekdays"
            )
        for d, (types, border) in zip(days, cells):
            if _is_red(border):
                _LOGGER.warning(
                    "Skipping %s-%02d-%02d: public-holiday alternative collection "
                    "(date not readable from the PDF)",
                    year,
                    month,
                    d,
                )
                continue
            for t in types:
                out.append(
                    Collection(date=date(year, month, d), t=t, icon=ICON_MAP.get(t))
                )
    return out


class Source:
    def __init__(self, postcode: str, address: str | None = None):
        self._postcode = postcode.strip().upper()
        self._address = re.sub(r"\s+", " ", address or "").strip().upper()

    async def fetch(self) -> list[Collection]:
        pc = re.sub(r"\s+", "", self._postcode)
        if len(pc) < 5:
            raise ValueError("Invalid postcode")
        async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS) as s:
            r = await s.post(
                URL,
                data={
                    "PostcodeBT": pc[:-3],
                    "PostcodeEND": pc[-3:],
                    "postback": "1",
                    "submit_btn": "SEARCH",
                },
                timeout=30,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for li in soup.select("div.list_downloads_sml li"):
                a = li.find("a", href=True)
                if not a:
                    continue
                addr = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
                addr = addr.replace("View Schedule", "").replace("\xa0", " ").strip()
                results.append((addr.upper(), a["href"]))
            if not results:
                raise ValueError(f"No addresses found for postcode {self._postcode}")

            if self._address:
                matches = [
                    (a, h)
                    for a, h in results
                    if a.startswith(self._address + " ")
                    or a.startswith(self._address + ",")
                ] or [(a, h) for a, h in results if self._address in a]
                if not matches:
                    raise ValueError(
                        f"Address {self._address!r} not found; options: "
                        + "; ".join(a for a, _ in results[:10])
                    )
                href = matches[0][1]
            else:
                hrefs = {h for _, h in results}
                if len(hrefs) != 1:
                    raise ValueError(
                        "Postcode spans several collection zones; supply address. "
                        "Options: " + "; ".join(a for a, _ in results[:10])
                    )
                href = results[0][1]

            m = re.search(r"/([A-Z]{3})-[^/]+\.pdf", href, re.I)
            if not m or m.group(1).upper() not in WEEKDAYS:
                raise ValueError(f"Unrecognised schedule link {href!r}")
            weekday = WEEKDAYS[m.group(1).upper()]

            pdf = await s.get(href, timeout=60)
            pdf.raise_for_status()

        today = date.today()
        entries = [c for c in _parse_pdf(pdf.content, weekday) if c.date >= today]
        if not entries:
            raise ValueError("No upcoming collections in schedule PDF")
        return entries
