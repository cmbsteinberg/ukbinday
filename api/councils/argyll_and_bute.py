"""Argyll and Bute: submit a postcode, then its zero-padded UPRN, to retrieve bin dates."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    parse_date,
    soup,
)

_BIN_URL = "https://www.argyll-bute.gov.uk/rubbish-and-recycling/household-waste/bin-collection"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_FORM_ID = "abc_bins_dates_lookup_form"
_FORM_OP = "Search for my bin collection details"


def _extract_form_build_id(html: str) -> str:
    match = re.search(r'name="form_build_id"\s+value="([^"]+)"', html)
    return match.group(1) if match else ""


def _parse_schedule(html: str) -> list[Collection]:
    table = soup(html).find("table", class_="table")
    if not table:
        return []

    collections = []
    today = datetime.now().date()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        bin_type = cells[0].get_text(strip=True)
        date_text = cells[1].get_text(strip=True)
        try:
            day = parse_date(f"{date_text} {today.year}")
            if day < today:
                day = parse_date(f"{date_text} {today.year + 1}")
        except ValueError:
            continue
        collections.append(Collection(day, bin_type))

    return collections


class ArgyllAndBute(Scraper):
    meta = Meta(
        title="Argyll and Bute Council",
        url="https://www.argyll-bute.gov.uk",
        lads=("S12000035",),
        cases={
            "Test_001": {"uprn": "125011723", "postcode": "PA28 6LJ"},
        },
    )
    requires = frozenset({"uprn", "postcode"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").replace(" ", "")
        uprn = address.need("uprn").zfill(12)

        r = await http.get(_BIN_URL, timeout=30)
        form_build_id = _extract_form_build_id(r.text)

        r = await http.post(
            _BIN_URL,
            timeout=30,
            data={
                "postcode": postcode,
                "form_build_id": form_build_id,
                "form_id": _FORM_ID,
                "op": _FORM_OP,
            },
        )
        form_build_id = _extract_form_build_id(r.text)

        r = await http.post(
            _BIN_URL,
            timeout=30,
            data={
                "postcode": postcode,
                "address": uprn,
                "form_build_id": form_build_id,
                "form_id": _FORM_ID,
                "op": _FORM_OP,
            },
        )
        return _parse_schedule(r.text)


SCRAPER = ArgyllAndBute()
