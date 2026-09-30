"""Medway: look up collections by UPRN, or resolve a UPRN from postcode and house number."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
)

_API_BASE = "https://api.medway.gov.uk/api"
_TITLE = "Medway Council"
_URL = "https://www.medway.gov.uk"
_HEADERS = {
    "Origin": "https://www.medway.gov.uk",
    "Referer": "https://www.medway.gov.uk/",
}


class Medway(Scraper):
    meta = Meta(
        title=_TITLE,
        url=_URL,
        lads=("E06000035",),
        cases={
            "known_uprn": {"uprn": "100062390963"},
            "by_postcode": {"postcode": "ME4 4AY", "house_number": "194-198"},
        },
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if uprn is None:
            if address.postcode is None or address.house_number is None:
                raise InputError(
                    "Must provide either a UPRN or both the Postcode and House Name or Number"
                )

            postcode = address.postcode.replace(" ", "").lower()
            response = await http.get(
                f"{_API_BASE}/addressing/getaddresses/{postcode}",
                timeout=30,
            )
            addresses = response.json()
            selected = match_address(
                address,
                addresses,
                text=lambda item: item.get("addressText", ""),
                uprn=lambda item: item.get("uprn"),
            )
            uprn = str(selected["uprn"])

        response = await http.get(f"{_API_BASE}/waste/getwasteday/{uprn}", timeout=30)
        data = response.json()
        collection_date = datetime.fromisoformat(data["nextCollection"]).date()

        return [Collection(collection_date, "Waste Collection")]


SCRAPER = Medway()
