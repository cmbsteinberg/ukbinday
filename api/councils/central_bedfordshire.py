"""Central Bedfordshire: search by postcode, match the property, then read its collection schedule."""

from __future__ import annotations

import re
from datetime import datetime

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
    soup,
    text_of,
)

_URL = "https://www.centralbedfordshire.gov.uk"
_BASE_PATH = "/waste-and-recycling/waste-collection-schedule"
_FIND_URL = f"{_URL}{_BASE_PATH}/find"
_VIEW_URL_TEMPLATE = f"{_URL}{_BASE_PATH}/view/{{uprn}}"

_BIN_TYPES = {
    "refuse (black bin)": "Refuse (black bin)",
    "recycling": "Recycling",
    "garden waste": "Garden waste",
    "food waste": "Food waste",
}
_TRAILING_COLLECTIONS_RE = re.compile(r"\s+collections?\s*$", re.IGNORECASE)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _split_bin_types(text: str) -> list[str]:
    """Split a collection sentence into its individual bin types."""
    text = _TRAILING_COLLECTIONS_RE.sub("", text.strip())
    text = text.replace(" and ", ", ")
    return [part.strip() for part in text.split(",") if part.strip()]


class CentralBedfordshire(Scraper):
    meta = Meta(
        title="Central Bedfordshire Council",
        url=_URL,
        lads=("E06000056",),
        cases={
            "Buttermere Avenue, Dunstable": {
                "postcode": "LU6 3PD",
                "house_number": "1",
                "street": "Buttermere Avenue",
            },
            "Chestnut Avenue, Biggleswade": {
                "postcode": "SG180LL",
                "house_number": "1",
                "street": "Chestnut Avenue",
            },
        },
    )
    requires = frozenset({"postcode"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if address.uprn is None and address.first_line is None:
            raise InputError("Central Bedfordshire needs a UPRN or address text")

        r = await http.get(
            _FIND_URL,
            params={"postcode": address.need("postcode")},
            timeout=30,
        )
        page = soup(r.text)

        address_select = page.find("select", id="edit-uprn")
        if address_select is None:
            raise AddressNotFound(
                f"No addresses were returned for postcode {address.postcode}; please check it and try again."
            )

        options = address_select.select("option[value]")
        option = match_address(
            address,
            options,
            text=text_of,
            uprn=lambda candidate: candidate.get("value"),
        )

        r = await http.get(
            _VIEW_URL_TEMPLATE.format(uprn=option["value"]),
            timeout=30,
        )
        page = soup(r.text)
        days = page.select(".waste-collection__day")
        if not days:
            raise UpstreamError(
                "Could not find any collections for this address; the page structure may have changed."
            )

        bins_by_date: dict[object, dict[str, str]] = {}
        for day in days:
            time_element = day.select_one(".waste-collection__day--day time")
            type_element = day.select_one(".waste-collection__day--type")
            if time_element is None or type_element is None or not time_element.get("datetime"):
                continue

            try:
                collection_date = datetime.strptime(
                    time_element["datetime"], "%d-%m-%Y"
                ).date()
            except ValueError:
                continue

            day_bins = bins_by_date.setdefault(collection_date, {})
            for bin_type in _split_bin_types(type_element.get_text()):
                key = bin_type.lower()
                day_bins[key] = _BIN_TYPES.get(key, bin_type)

        return [
            Collection(collection_date, bin_type)
            for collection_date, day_bins in bins_by_date.items()
            for bin_type in day_bins.values()
        ]


SCRAPER = CentralBedfordshire()
