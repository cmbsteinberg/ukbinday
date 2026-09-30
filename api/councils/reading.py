"""Reading: look up a UPRN by postcode and house number when needed, then fetch its collections."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
)

_UPRN_URL = "https://api.reading.gov.uk/rbc/getaddresses"
_COLLECTION_URL = "https://api.reading.gov.uk/api/collections"

_COLLECTIONS = {
    "Domestic Waste Collection Service": "Rubbish",
    "Recycling Collection Service": "Recycling",
    "Food Waste Collection Service": "Food Waste",
    "Garden Waste Collection Service": "Garden Waste",
}


class Reading(Scraper):
    meta = Meta(
        title="Reading Council",
        url="https://reading.gov.uk",
        lads=("E06000038",),
        cases={
            "known_uprn": {"uprn": "310027679"},
            "unknown_uprn_by_number": {"postcode": "RG31 5PN", "house_number": "65"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if uprn is None:
            if address.postcode is None or address.house_number is None:
                raise InputError(
                    "Must provide either a UPRN or both the Postcode and House Name or Number"
                )
            response = await http.get(f"{_UPRN_URL}/{address.postcode}")
            addresses = response.json()["Addresses"]
            if addresses is None:
                raise AddressNotFound(f"No addresses found for postcode {address.postcode}")
            selected = match_address(
                address,
                addresses,
                text=lambda candidate: candidate["SiteShortAddress"],
                uprn=lambda candidate: candidate["AccountSiteUprn"],
            )
            uprn = selected["AccountSiteUprn"]

        response = await http.get(f"{_COLLECTION_URL}/{uprn}")
        return [
            Collection(
                datetime.strptime(collection["date"], "%d/%m/%Y %H:%M:%S").date(),
                _COLLECTIONS[collection["service"]],
            )
            for collection in response.json()["collections"]
        ]


SCRAPER = Reading()
