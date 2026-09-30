"""Northumberland: submit a postcode, then a UPRN, to retrieve the collection schedule."""

from __future__ import annotations

import re

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    parse_date,
    soup,
)

_BASE_URL = "https://bincollection.northumberland.gov.uk"


def _extract_csrf(html: str) -> str:
    match = re.search(r'name=["\']_csrf["\'][^>]*value=["\']([^"\']+)', html)
    return match.group(1) if match else ""


def _parse_schedule(html: str) -> list[Collection]:
    page = soup(html)
    table = page.find("table")
    if table is None:
        return []

    collections: list[Collection] = []
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 3:
            continue

        date_text = cells[0].get_text(strip=True)
        bin_type = cells[2].get_text(strip=True)
        try:
            day = parse_date(date_text)
        except ValueError:
            continue
        collections.append(Collection(day, bin_type))

    return collections


class Northumberland(Scraper):
    meta = Meta(
        title="Northumberland County Council",
        url="https://www.northumberland.gov.uk",
        lads=("E06000057",),
        cases={
            "Test_001": {"uprn": "10096302588", "postcode": "NE65 0ZP"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.postcode or ""

        response = await http.get(f"{_BASE_URL}/postcode", timeout=30.0)
        csrf = _extract_csrf(response.text)

        response = await http.post(
            f"{_BASE_URL}/postcode",
            data={"_csrf": csrf, "postcode": postcode},
            timeout=30.0,
        )
        csrf = _extract_csrf(response.text)

        response = await http.post(
            f"{_BASE_URL}/address-select",
            data={"_csrf": csrf, "address": address.need("uprn")},
            timeout=30.0,
        )
        return _parse_schedule(response.text)


SCRAPER = Northumberland()
