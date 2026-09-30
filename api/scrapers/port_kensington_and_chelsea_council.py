"""Royal Borough of Kensington and Chelsea bin collections (street lookup).

Flow (plain HTTP, no browser):
  1. GET https://www.rbkc.gov.uk/bincollections/default.aspx — an ASP.NET Core
     MVC form (not WebForms: no __VIEWSTATE) with a <select name="Street">
     dropdown and a hidden __RequestVerificationToken antiforgery field. The
     dropdown option values are the street names, space-padded.
  2. POST Street + __RequestVerificationToken back to the same URL. The
     response contains a table, one row per property-number range on that
     street: property numbers (e.g. "[2 - 80a evens] & [9 - 63 odds]" or
     "All"), general waste and recycling weekdays, food waste weekday.

The service is keyed by STREET, not UPRN, so the Source takes `street`
(plus an optional `house_number` to choose between number ranges), or a full
`address` string from which the street and number are derived by matching
against the dropdown.

Data-quality note: the source publishes collection *weekdays* only, not
dates. Each weekday is returned once, dated at its next upcoming occurrence
(same convention as port_hertsmere_borough_council). No multi-week
projection is fabricated. A blank food waste cell means the council lists no
food waste day for that range and nothing is emitted.

Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

import logging
import re
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]

TITLE = "Royal Borough of Kensington and Chelsea"
DESCRIPTION = (
    "Source for rbkc.gov.uk bin collections (street lookup; collection weekdays "
    "only — dates are next-occurrence projections)."
)
URL = "https://www.rbkc.gov.uk/bins-and-recycling"
TEST_CASES = {
    "Portobello Road 100": {"street": "Portobello Road", "house_number": "100"},
    "Sloane Street": {"street": "Sloane Street"},
    "Address string": {"address": "12 Abingdon Road, London"},
}

HOW_TO_GET_ARGUMENTS_DESCRIPTION = {
    "en": "Use the street name as listed at https://www.rbkc.gov.uk/bincollections/default.aspx; add house_number if the street has several number ranges.",
}

# The site 403s a full Chrome UA string but accepts a bare one.
HEADERS = {"User-Agent": "Mozilla/5.0"}

_LOGGER = logging.getLogger(__name__)

PAGE_URL = "https://www.rbkc.gov.uk/bincollections/default.aspx"
_DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _next_weekday(day_name: str) -> date:
    today = date.today()
    delta = (_DAYS.index(day_name) - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _range_matches(spec: str, number: int) -> bool:
    """Match a number against e.g. '[2 - 80a evens] & [9 - 63 odds]' or 'All'."""
    if spec.strip().lower() in ("all", ""):
        return True
    for part in re.findall(r"\[([^\]]*)\]", spec):
        m = re.match(r"\s*(\d+)\w*\s*(?:-\s*(\d+)\w*)?\s*(odds|evens)?", part, re.I)
        if not m:
            continue
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        parity = (m.group(3) or "").lower()
        if not lo <= number <= hi:
            continue
        if parity == "odds" and number % 2 == 0:
            continue
        if parity == "evens" and number % 2 == 1:
            continue
        return True
    return False


class Source:
    def __init__(self, street: str = "", house_number: str | int = "", address: str = ""):
        self._street = str(street or "").strip()
        self._number = str(house_number or "").strip()
        self._address = str(address or "").strip()
        if not (self._street or self._address):
            raise ValueError("street (or address) is required")

    def _resolve_street(self, options: dict[str, str]) -> str:
        """Map user input to a dropdown key (lowercased name -> raw value)."""
        if self._street:
            key = self._street.lower()
            if key in options:
                return options[key]
        haystack = f"{self._street} {self._address}".lower()
        matches = [n for n in options if n and re.search(rf"\b{re.escape(n)}\b", haystack)]
        if not matches:
            raise ValueError(f"Street not found in RBKC street list: {self._street or self._address!r}")
        return options[max(matches, key=len)]

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True) as session:
            r1 = await session.get(PAGE_URL, headers=HEADERS, timeout=30)
            r1.raise_for_status()
            soup = BeautifulSoup(r1.text, "html.parser")
            token = soup.find("input", attrs={"name": "__RequestVerificationToken"})
            select = soup.find("select", attrs={"name": "Street"})
            if not token or not select:
                raise ValueError("Street form not found on page")
            options = {
                o["value"].strip().lower(): o["value"]
                for o in select.find_all("option")
                if o.get("value", "").strip()
            }
            value = self._resolve_street(options)

            r2 = await session.post(
                PAGE_URL,
                data={"Street": value, "__RequestVerificationToken": token["value"]},
                headers={**HEADERS, "Referer": PAGE_URL},
                timeout=30,
            )
            r2.raise_for_status()

        return self._parse(r2.text)

    def _house_number(self) -> int | None:
        m = re.search(r"\d+", self._number) or re.match(r"\s*(\d+)", self._address)
        return int(m.group(0)) if m else None

    def _parse(self, html: str) -> list[Collection]:
        table = BeautifulSoup(html, "html.parser").find("table", class_="table")
        if not table:
            raise ValueError("No collection table returned")
        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) >= 6:
                rows.append(cells)
        if not rows:
            raise ValueError("No collection rows returned")

        chosen = rows[0]
        if len(rows) > 1:
            number = self._house_number()
            match = (
                next((r for r in rows if _range_matches(r[1], number)), None)
                if number is not None
                else None
            )
            if match is None:
                _LOGGER.warning("Several number ranges; using first (%s)", rows[0][1])
            else:
                chosen = match

        entries: list[Collection] = []
        for cell, label, icon in (
            (chosen[4], "General waste and recycling", Icons.GENERAL_WASTE),
            (chosen[5], "Food waste", Icons.BIO_KITCHEN),
        ):
            for day in re.findall("|".join(_DAYS), cell):
                entries.append(Collection(date=_next_weekday(day), t=label, icon=icon))
        if not entries:
            raise ValueError("No collection weekdays found")
        return sorted(entries, key=lambda c: c.date)
