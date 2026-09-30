"""East Staffordshire: search collection dates by postcode, then read the property's schedule."""

from __future__ import annotations

import re
from datetime import date

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
    parse_date,
    soup,
    text_of,
)

_BASE_URL = "https://www.eaststaffsbc.gov.uk/bins-rubbish-recycling/collection-dates"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
_DAY_PATTERN = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(\d+)(?:st|nd|rd|th)?\s+(\w+)"
)


def _parse_date(text: str) -> date | None:
    match = _DAY_PATTERN.search(text)
    if not match:
        return None
    try:
        return parse_date(match.group(0))
    except ValueError:
        return None


async def _resolve_property_id(address: Address, http: Http) -> str:
    r = await http.get(
        _BASE_URL,
        params={"postal_code": address.need("postcode")},
        timeout=30.0,
    )
    page = soup(r.text)
    anchors = [
        anchor
        for anchor in page.find_all("a", href=True)
        if "/collection-dates/" in anchor.get("href", "")
    ]
    if not address.first_line:
        raise InputError("East Staffordshire needs address text to find a property")

    anchor = match_address(address, anchors, text=text_of)
    return anchor["href"].rstrip("/").rsplit("/", 1)[-1]


def _parse_schedule(html: str) -> list[Collection]:
    page = soup(html)
    entries: list[Collection] = []

    next_section = page.find("div", class_="collection-next")
    if next_section:
        heading = next_section.find("h2")
        day = _parse_date(text_of(heading))
        if day:
            for item in next_section.find_all("div", class_="field__item"):
                entries.append(Collection(day, item.get_text(strip=True)))

    for li in page.find_all("li"):
        text = str(li.contents[0]).strip() if li.contents else ""
        day = _parse_date(text)
        if not day:
            continue
        for item in li.find_all("div", class_="field__item"):
            entries.append(Collection(day, item.get_text(strip=True)))

    return entries


class EastStaffordshire(Scraper):
    meta = Meta(
        title="East Staffordshire Borough Council",
        url="https://www.eaststaffsbc.gov.uk",
        lads=("E07000193",),
        cases={
            "Test_001": {
                "postcode": "DE13 0BS",
                "house_number": "1",
                "street": "Fairham Road",
            },
        },
    )
    requires = frozenset({"postcode"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        property_id = await _resolve_property_id(address, http)
        r = await http.get(f"{_BASE_URL}/{property_id}", timeout=30.0)
        return _parse_schedule(r.text)


SCRAPER = EastStaffordshire()
