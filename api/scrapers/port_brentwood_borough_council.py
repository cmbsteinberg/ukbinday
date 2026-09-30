"""Brentwood Borough Council bin collections (GeoServer WFS + route calendar PDF).

The council's "Collection day map" (MapStore at maps.brentwood.gov.uk) is backed
by an unauthenticated GeoServer. Flow:

1. WFS GetFeature on layer ``geodata:Recycling and Waste`` with
   ``CQL_FILTER=uprn='<UPRN>'`` -> per-property route, garden/glass round
   flags and ``calendar`` (link to the route's printable PDF calendar,
   ``https://www.brentwood.gov.uk/media/<id>``).
2. Download the route PDF ("MY COLLECTION CALENDAR", one page, ~8 months of
   weekly dates published by the council).
3. Parse the PDF with pdfplumber: month headers -> date boxes. A filled box is
   a BLUE-sack week (paper and card, food waste, refuse, glass, garden); an
   outlined box is a WHITE-sack week (plastic and cans, food waste, refuse).
   Legend from the PDF: both sacks are collected with food waste and refuse.

Data-quality notes:
- Dates come straight from the council PDF; nothing is extrapolated. The PDF
  only covers the current schedule period (currently April - November 2026),
  so results run out at the end of that period until the council republishes.
- The PDF header weekday (e.g. "THURSDAY ROUTE 9") is authoritative; the
  layer's ``residual_day`` is sometimes stale, so it is ignored.
- The council PDFs contain occasional typos (Route 9 prints "19" July for
  Thursday 16 July). A date whose weekday disagrees with the header is snapped
  to the nearest matching weekday within +/-3 days.
- Garden/glass are only emitted when the layer flags the property with
  ``garden_round == 'GW'`` / ``glass_round == 'GL'``.

Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

import io
import logging
import re
from datetime import date, timedelta

import httpx

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentNotFound

TITLE = "Brentwood Borough Council"
DESCRIPTION = "Source for brentwood.gov.uk bin collections (GeoServer property layer + route calendar PDF)."
URL = "https://www.brentwood.gov.uk/collection-day"
TEST_CASES = {
    "127 Greenshaw, Brentwood CM14 4YP (Thursday, Route 9)": {"uprn": "100090336817"},
    "Route 1 (Monday)": {"uprn": "10093276507"},
    "Route 8 (Friday)": {"uprn": "10093274131"},
}

_LOGGER = logging.getLogger(__name__)

_WFS_URL = "https://maps.brentwood.gov.uk/geoserver/ows"
_LAYER = "geodata:Recycling and Waste"
_MEDIA_RE = re.compile(r"^https://www\.brentwood\.gov\.uk/media/\d+$")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
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
        ],
        start=1,
    )
}
_WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

PARAM_DESCRIPTIONS = {
    "en": {"uprn": "Unique Property Reference Number of the property"}
}

HOW_TO_GET_ARGUMENTS_DESCRIPTION = {
    "en": "Find your UPRN at https://www.findmyaddress.co.uk/ (or via the API's address lookup)."
}


def _parse_calendar(pdf_bytes: bytes) -> tuple[int, list[tuple[date, bool]]]:
    """Return (header weekday index, [(date, is_blue_week)])."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        boxes = [
            r
            for r in page.rects
            if 15 < r["x1"] - r["x0"] < 25 and 15 < r["bottom"] - r["top"] < 25
        ]

    weekday = None
    for w in words:
        if w["text"].upper() in _WEEKDAYS and w["top"] < 160:
            weekday = _WEEKDAYS.index(w["text"].upper())
            break
    if weekday is None:
        raise ValueError("route weekday not found in calendar PDF")

    headers = []
    for i, w in enumerate(words[:-1]):
        nxt = words[i + 1]
        if (
            w["text"].upper() in _MONTHS
            and re.fullmatch(r"20\d\d", nxt["text"])
            and abs(nxt["top"] - w["top"]) < 3
        ):
            headers.append((w["x0"], w["top"], _MONTHS[w["text"].upper()], int(nxt["text"])))

    out: list[tuple[date, bool]] = []
    for x0, top, month, year in headers:
        for w in words:
            if not re.fullmatch(r"\d{1,2}", w["text"]):
                continue
            if not (top + 10 < w["top"] < top + 45 and x0 - 10 <= w["x0"] < x0 + 190):
                continue
            cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
            box = next(
                (b for b in boxes if b["x0"] <= cx <= b["x1"] and b["top"] <= cy <= b["bottom"]),
                None,
            )
            if box is None:
                continue
            try:
                d = date(year, month, int(w["text"]))
            except ValueError:
                continue
            if d.weekday() != weekday:
                # council typo: snap to nearest matching weekday within +/-3 days
                for off in (-1, 1, -2, 2, -3, 3):
                    cand = d + timedelta(days=off)
                    if cand.weekday() == weekday:
                        d = cand
                        break
                else:
                    continue
            out.append((d, bool(box["fill"])))
    return weekday, sorted(set(out))


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = str(uprn).strip()

    async def fetch(self) -> list[Collection]:
        if not self._uprn.isdigit():
            raise SourceArgumentNotFound("uprn", self._uprn, "UPRN must be numeric")

        async with httpx.AsyncClient(
            follow_redirects=True, headers={"User-Agent": _USER_AGENT}, timeout=60
        ) as client:
            r = await client.get(
                _WFS_URL,
                params={
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "typeNames": _LAYER,
                    "outputFormat": "application/json",
                    "CQL_FILTER": f"uprn='{self._uprn}'",
                    "propertyName": "uprn,garden_round,glass_round,calendar,address",
                },
            )
            r.raise_for_status()
            feats = r.json().get("features", [])
            if not feats:
                raise SourceArgumentNotFound(
                    "uprn", self._uprn, "UPRN not found in Brentwood collection layer"
                )
            props = feats[0]["properties"]
            cal = props.get("calendar") or ""
            if not _MEDIA_RE.match(cal):
                raise SourceArgumentNotFound(
                    "uprn",
                    self._uprn,
                    "property has no published collection calendar (non-household or unassigned round)",
                )
            pdf = await client.get(cal)
            pdf.raise_for_status()

        _weekday, dates = _parse_calendar(pdf.content)
        if not dates:
            raise ValueError("no dates parsed from Brentwood calendar PDF")

        garden = props.get("garden_round") == "GW"
        glass = props.get("glass_round") == "GL"
        today = date.today()
        entries: list[Collection] = []
        for d, blue in dates:
            if d < today:
                continue
            entries.append(Collection(date=d, t="Refuse", icon=Icons.GENERAL_WASTE))
            entries.append(Collection(date=d, t="Food Waste", icon=Icons.BIO_KITCHEN))
            if blue:
                entries.append(Collection(date=d, t="Paper and Card (Blue Sack)", icon=Icons.PAPER))
                if glass:
                    entries.append(Collection(date=d, t="Glass", icon=Icons.GLASS))
                if garden:
                    entries.append(Collection(date=d, t="Garden Waste", icon=Icons.GARDEN))
            else:
                entries.append(
                    Collection(date=d, t="Plastic and Cans (White Sack)", icon=Icons.PLASTIC_PACKAGING)
                )
        return entries
