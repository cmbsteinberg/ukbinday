"""Wychavon: look up an address by postcode, then request its collection schedule by UPRN."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    match_address,
    soup,
)

_BASE_URL = "https://selfservice.wychavon.gov.uk"
_ADDRESS_URL = f"{_BASE_URL}/sw2AddressLookupWS/jaxrs/PostCode"
_SEARCH_URL = f"{_BASE_URL}/wdcroundlookup/HandleSearchScreen"
_JS_ENABLED_TOKEN = "TsOkrIPJrqo5nVGVChHj"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _parse_schedule(html: str) -> list[Collection]:
    page = soup(html)
    entries: list[Collection] = []

    for table in page.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            bin_type_cell = cells[1].get_text(strip=True)
            date_cell = cells[2]

            bin_type_match = re.match(r"^([\w\s-]+collection)", bin_type_cell, re.I)
            if not bin_type_match:
                continue
            bin_type = bin_type_match.group(1).strip()

            strong = date_cell.find("strong")
            if not strong:
                continue
            date_text = strong.get_text(strip=True)
            date_match = re.search(r"(\d{1,2}/\d{2}/\d{4})", date_text)
            if not date_match:
                continue

            try:
                day = datetime.strptime(date_match.group(1), "%d/%m/%Y").date()
            except ValueError:
                continue

            entries.append(Collection(date=day, type=bin_type))

    return entries


class Wychavon(Scraper):
    meta = Meta(
        title="Wychavon District Council",
        url="https://www.wychavon.gov.uk",
        lads=("E07000238",),
        cases={
            "Test_001": {"uprn": "100120716273", "postcode": "WR3 7RU"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        r = await http.get(
            _ADDRESS_URL,
            params={
                "simple": "T",
                "pcode": address.postcode or "",
                "authority": "WDC",
                "historical": "",
            },
            timeout=60.0,
        )
        addresses = r.json().get("jArray", [])
        selected = match_address(
            address,
            addresses,
            text=lambda candidate: candidate.get("Address_Short", ""),
            uprn=lambda candidate: candidate.get("UPRN"),
        )

        r = await http.post(
            _SEARCH_URL,
            timeout=60.0,
            data={
                "nmalAddrtxt": address.postcode or "",
                "alAddrsel": uprn,
                "txtPage": "std",
                "txtSearchPerformedFlag": "false",
                "futuredate": "",
                "errstatus": "",
                "address": selected.get("Address_Short", ""),
                "jsenabled": _JS_ENABLED_TOKEN,
                "btnSubmit": "Next",
            },
        )
        return _parse_schedule(r.text)


SCRAPER = Wychavon()
