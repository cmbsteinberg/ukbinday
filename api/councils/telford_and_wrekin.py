"""Telford and Wrekin: search by postcode when needed, then fetch collections by UPRN."""

from __future__ import annotations

import json

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
    parse_date,
)

_ADDRESS_SEARCH_URL = "https://dac.telford.gov.uk/BinDayFinder/Find/PostcodeSearch"
_COLLECTION_URL = "https://dac.telford.gov.uk/BinDayFinder/Find/PropertySearch"


class TelfordAndWrekin(Scraper):
    meta = Meta(
        title="Telford and Wrekin Council",
        url="https://www.telford.gov.uk/bins-and-recycling/check-your-collection-day/",
        lads=("E06000020",),
        cases={
            "10 Long Row Drive, Lawley": {"uprn": "452097493"},
            "126 Dunsheath, Telford": {"postcode": "TF3 2DA", "house_number": "126"},
            "11 Pinewoods, Telford": {"postcode": "TF10 9LN", "house_number": "11"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if not uprn:
            if address.postcode is None or address.house_number is None:
                raise InputError("Telford and Wrekin needs a UPRN or a postcode and house number")

            r = await http.get(
                _ADDRESS_SEARCH_URL,
                params={"postcode": address.postcode},
                check=False,
            )
            if r.status_code == 500:
                raise InputError("Postcode is not in the correct format or service is unavailable")

            addresses = json.loads(r.json())
            properties = addresses["properties"]
            if not properties:
                raise AddressNotFound(f"No properties found for postcode {address.postcode}")

            property_match = match_address(
                address,
                properties,
                text=lambda item: item["PrimaryName"],
                uprn=lambda item: item["UPRN"],
            )
            uprn = property_match["UPRN"]

        r = await http.get(_COLLECTION_URL, params={"uprn": uprn})
        collections = json.loads(r.json())["bincollections"]

        return [
            Collection(parse_date(collection["nextDate"]), collection["name"])
            for collection in collections
        ]


SCRAPER = TelfordAndWrekin()
