"""Royal Borough of Kensington and Chelsea: submit a street to its ASP.NET Core form and read collection weekdays."""

from __future__ import annotations

import logging
import re

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    next_weekday,
    soup,
)

PAGE_URL = "https://www.rbkc.gov.uk/bincollections/default.aspx"
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_LOGGER = logging.getLogger(__name__)


def _range_matches(spec: str, number: int) -> bool:
    """Match a number against e.g. '[2 - 80a evens] & [9 - 63 odds]' or 'All'."""
    if spec.strip().lower() in ("all", ""):
        return True
    for part in re.findall(r"\[([^\]]*)\]", spec):
        match = re.match(r"\s*(\d+)\w*\s*(?:-\s*(\d+)\w*)?\s*(odds|evens)?", part, re.I)
        if not match:
            continue
        low = int(match.group(1))
        high = int(match.group(2)) if match.group(2) else low
        parity = (match.group(3) or "").lower()
        if not low <= number <= high:
            continue
        if parity == "odds" and number % 2 == 0:
            continue
        if parity == "evens" and number % 2 == 1:
            continue
        return True
    return False


def _resolve_street(options: dict[str, str], street: str | None, label: str | None) -> str:
    """Map user input to a dropdown key (lowercased name -> raw value)."""
    if street:
        key = street.lower()
        if key in options:
            return options[key]
    haystack = f"{street or ''} {label or ''}".lower()
    matches = [name for name in options if name and re.search(rf"\b{re.escape(name)}\b", haystack)]
    if not matches:
        raise AddressNotFound(f"Street not found in RBKC street list: {street or label!r}")
    return options[max(matches, key=len)]


class KensingtonAndChelsea(Scraper):
    meta = Meta(
        title="Royal Borough of Kensington and Chelsea",
        url="https://www.rbkc.gov.uk/bins-and-recycling",
        lads=("E09000020",),
        cases={
            "Portobello Road 100": {
                "street": "Portobello Road",
                "house_number": "100",
            },
            "Sloane Street": {"street": "Sloane Street"},
            "Address string": {"address": "12 Abingdon Road, London"},
        },
    )
    requires = frozenset()
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if not (address.street or address.label):
            raise InputError("street (or address) is required")

        r1 = await http.get(PAGE_URL, timeout=30)
        page = soup(r1.text)
        token = page.find("input", attrs={"name": "__RequestVerificationToken"})
        select = page.find("select", attrs={"name": "Street"})
        if token is None or select is None:
            raise UpstreamError("Street form not found on page")

        options = {
            option["value"].strip().lower(): option["value"]
            for option in select.find_all("option")
            if option.get("value", "").strip()
        }
        value = _resolve_street(options, address.street, address.label)

        r2 = await http.post(
            PAGE_URL,
            data={
                "Street": value,
                "__RequestVerificationToken": token.get("value", ""),
            },
            headers={"Referer": PAGE_URL},
            timeout=30,
        )
        return self._parse(r2.text, address)

    def _parse(self, html: str, address: Address) -> list[Collection]:
        table = soup(html).find("table", class_="table")
        if table is None:
            raise UpstreamError("No collection table returned")

        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) >= 6:
                rows.append(cells)
        if not rows:
            raise UpstreamError("No collection rows returned")

        chosen = rows[0]
        if len(rows) > 1:
            number_text = address.house_number or ""
            number_match = re.search(r"\d+", number_text) or re.match(
                r"\s*(\d+)", address.label or ""
            )
            number = int(number_match.group(0)) if number_match else None
            match = (
                next((row for row in rows if _range_matches(row[1], number)), None)
                if number is not None
                else None
            )
            if match is None:
                _LOGGER.warning("Several number ranges; using first (%s)", rows[0][1])
            else:
                chosen = match

        collections = []
        for cell, label in (
            (chosen[4], "General waste and recycling"),
            (chosen[5], "Food waste"),
        ):
            for day in re.findall("|".join(_DAYS), cell):
                collections.append(Collection(next_weekday(day, include_today=False), label))
        if not collections:
            raise UpstreamError("No collection weekdays found")
        return collections


SCRAPER = KensingtonAndChelsea()
