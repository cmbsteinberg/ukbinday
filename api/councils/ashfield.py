"""Ashfield: look up a UPRN by postcode and address text, then fetch its collections."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
    match_address,
)

_ADDRESS_SEARCH_URL = "https://www.ashfield.gov.uk/api/address/search/{postcode}"
_COLLECTION_URL = "https://www.ashfield.gov.uk/api/address/collections/{uprn}"

_NAMES = {
    "Residual Waste Collection Service": "Red (rubbish)",
    "Domestic Recycling Collection Service": "Green (recycling)",
    "Domestic Glass Collection Service": "Blue (glass)",
    "Garden Waste Collection Service": "Brown (garden)",
}


def _dpa(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("DPA")
    return value if isinstance(value, dict) else {}


def _candidate_text(item: dict[str, Any], *, name: bool) -> str:
    dpa = _dpa(item)
    if name:
        return str(dpa.get("BUILDING_NAME") or "")
    return f"{dpa.get('BUILDING_NUMBER', '')} {dpa.get('BUILDING_NAME', '')}".strip()


class Ashfield(Scraper):
    meta = Meta(
        title="Ashfield District Council",
        url="https://www.ashfield.gov.uk",
        lads=("E07000170",),
        cases={
            "11 Maun View Gardens, Sutton-in-Ashfield": {"uprn": "10001336299"},
            "1 Acacia Avenue, Kirkby-in-Ashfield": {
                "postcode": "NG17 9BH",
                "house_number": "1",
            },
            "Council Offices, Kirkby-in-Ashfield": {
                "postcode": "NG17 8ZA",
                "name": "COUNCIL OFFICES",
            },
        },
    )
    requires = frozenset()
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if uprn is None:
            postcode = address.postcode
            name = address.extra.get("name")
            house_number = address.house_number
            if postcode is None:
                raise InputError("postcode is required when uprn is not provided")
            if not (name or house_number):
                raise InputError(
                    "Either name or house_number must be provided when uprn is not provided"
                )

            r = await http.get(_ADDRESS_SEARCH_URL.format(postcode=postcode), timeout=30)
            addresses: list[dict[str, Any]] = r.json()["results"]
            if not addresses:
                raise AddressNotFound(f"No addresses found for postcode {postcode}")

            matching_address = address
            if name:
                matching_address = replace(
                    address,
                    house_number=None,
                    street=None,
                    label=name,
                )

            selected = match_address(
                matching_address,
                addresses,
                text=lambda item: _candidate_text(item, name=bool(name)),
                uprn=lambda item: _dpa(item).get("UPRN"),
            )
            uprn_value = _dpa(selected).get("UPRN")
            if not uprn_value:
                raise AddressNotFound(f"No property matching {name or house_number!r}")
            uprn = str(int(uprn_value))
        else:
            uprn = str(int(uprn))

        r = await http.get(_COLLECTION_URL.format(uprn=uprn), timeout=30)
        collections = r.json()["collections"]

        entries: list[Collection] = []
        if collections:
            for collection in collections:
                service = collection["service"]
                entries.append(
                    Collection(
                        date=datetime.strptime(
                            collection["date"], "%d/%m/%Y %H:%M:%S"
                        ).date(),
                        type=_NAMES.get(service, service),
                    )
                )
        return entries


SCRAPER = Ashfield()
