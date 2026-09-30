"""Uttlesford: resolve a house value from postcode and address text, then read its collection table."""

from __future__ import annotations

import re

from bs4 import Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    parse_date,
    soup,
    text_of,
)

URL = "https://www.uttlesford.gov.uk"
API_URL = "https://bins.uttlesford.gov.uk/collections.php?house={house}"
ADDRESS_URL = "https://bins.uttlesford.gov.uk/result.php?postcode={postcode}"

_TEXT_MAP = {
    "black": "Black (Non-Recyclable)",
    "green": "Green (Dry Recycling)",
    "brown": "Brown (Food Waste)",
}


def _trim_ordinal(text: str) -> str:
    return re.sub(r"(\d)(st|nd|rd|th)", r"\1", text)


async def _resolve_house(address: Address, http: Http) -> str:
    """Look up the council's house value using postcode and address text."""
    if not address.postcode or not address.house_number:
        raise InputError("Uttlesford needs a house value or both postcode and house number")

    postcode = re.sub(r"\s+", "", address.postcode).upper()
    response = await http.get(ADDRESS_URL.format(postcode=postcode))
    options = [
        option
        for option in soup(response.text).find_all("option")
        if isinstance(option, Tag) and option.get("value")
    ]
    selected = match_address(address, options, text=text_of)
    value = selected.get("value")
    if not isinstance(value, str):
        raise AddressNotFound("No matching Uttlesford property was found")
    return value


class Uttlesford(Scraper):
    meta = Meta(
        title="Uttlesford District Council",
        url=URL,
        lads=("E07000077",),
        cases={
            "Brook Cottage, CM6 1LW": {"house": "29142-Tuesday"},
            "Springfields, CM6 1BP": {"house": "26455-Thursday"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        house = address.extra.get("house")
        if house is None:
            house = await _resolve_house(address, http)

        response = await http.get(API_URL.format(house=house))
        tables = soup(response.text).find_all("table")
        if len(tables) < 2:
            raise UpstreamError("Uttlesford's collections page has no schedule table")

        collections: list[Collection] = []
        for row in tables[1].find_all("tr"):
            fields = row.findChildren()
            datestr = _trim_ordinal(fields[3].get_text())
            day = parse_date(datestr)

            image = row.find("img")
            image_src = image.get("src", "") if isinstance(image, Tag) else ""
            collection_type = "green" if "green" in image_src else "black"
            collections.append(Collection(day, _TEXT_MAP[collection_type]))
            collections.append(Collection(day, _TEXT_MAP["brown"]))

        return collections


SCRAPER = Uttlesford()
