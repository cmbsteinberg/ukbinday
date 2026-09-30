"""Thanet: look up collections by UPRN, or search by postcode and match an address."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
    match_address,
)

_API_URL = (
    "https://www.thanet.gov.uk/wp-content/mu-plugins/collection-day/"
    "incl/mu-collection-day-calls.php"
)

_TYPES = {
    "Refuse": "Rubbish",
    "BlueRecycling": "Mixed Recycling (Blue)",
    "RedRecycling": "Paper & Card (Red)",
    "Food": "Food Waste",
    "Garden": "Garden",
}


class Thanet(Scraper):
    meta = Meta(
        title="Thanet District Council",
        url="https://thanet.gov.uk",
        lads=("E07000114",),
        cases={
            "houseName": {"postcode": "CT7 9SL", "address": "Forus"},
            "houseNumber": {
                "postcode": "CT7 9SL",
                "house_number": "6",
                "street": "Gordon Square",
            },
            "uprn": {"uprn": "100061108233"},
        },
    )
    requires = frozenset()
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if uprn is None:
            if address.postcode is None or address.first_line is None:
                raise InputError("Thanet needs a UPRN or a postcode and first line of address")
            addresses_json = (
                await http.get(
                    _API_URL,
                    params={"searchAddress": address.postcode},
                    timeout=30,
                )
            ).json()
            candidates = list(addresses_json.items())
            candidate = match_address(
                address,
                candidates,
                text=lambda item: item[1],
                uprn=lambda item: item[0],
            )
            uprn = candidate[0]

        collections_json = (
            await http.get(
                _API_URL,
                params={"pAddress": uprn},
                timeout=30,
            )
        ).json()

        collections = []
        for collection in collections_json:
            bin_type = collection["type"]
            if bin_type not in _TYPES:
                continue
            for date_key in ("nextDate", "previousDate"):
                collections.append(
                    Collection(
                        date=datetime.strptime(
                            collection[date_key][:10], "%d/%m/%Y"
                        ).date(),
                        type=_TYPES[bin_type],
                    )
                )
        return collections


SCRAPER = Thanet()
