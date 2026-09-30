"""Canterbury: search addresses by postcode, then request bin dates for the matched UPRN and USRN."""

from __future__ import annotations

import json
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
    match_address,
)

_API_URLS = {
    "address_search": "https://trsewmllv7.execute-api.eu-west-2.amazonaws.com/dev/address",
    "collection": "https://n6ljrw455m.execute-api.eu-west-2.amazonaws.com/prod/get-bin-dates",
}
_POST_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://www.canterbury.gov.uk",
    "Referer": "https://www.canterbury.gov.uk/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
    "Accept": "*/*",
}


def _candidate_text(candidate: dict[str, Any]) -> str:
    """Build matchable address text from Canterbury's LPI fields."""
    lpi = candidate["LPI"]
    parts = [
        str(lpi[key]).strip()
        for key in ("SAO_TEXT", "PAO_TEXT")
        if lpi.get(key)
    ]
    number = lpi.get("PAO_START_NUMBER")
    if number:
        parts.append(f"{number}{lpi.get('PAO_START_SUFFIX') or ''}")
    return " ".join(parts)


class Canterbury(Scraper):
    meta = Meta(
        title="Canterbury City Council",
        url="https://canterbury.gov.uk",
        lads=("E07000106",),
        cases={
            "houseNumber": {"postcode": "CT6 8RU", "house_number": "63"},
            "houseName": {"postcode": "CT6 8RU", "house_number": "KOWLOON"},
        },
    )
    requires = frozenset({"postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if not address.uprn and not address.house_number and not address.first_line:
            raise InputError("Canterbury needs a UPRN or address text")

        response = await http.get(
            _API_URLS["address_search"],
            params={"postcode": address.need("postcode"), "type": "standard"},
        )
        addresses = response.json()["results"]
        if not addresses:
            raise AddressNotFound(f"Canterbury has no addresses for {address.postcode}")

        selected = match_address(
            address,
            addresses,
            text=_candidate_text,
            uprn=lambda candidate: candidate["LPI"].get("UPRN"),
        )
        lpi = selected["LPI"]

        response = await http.post(
            _API_URLS["collection"],
            json={"uprn": lpi["UPRN"], "usrn": lpi["USRN"]},
            headers=_POST_HEADERS,
        )
        dates = response.json()["dates"]
        collections_raw = json.loads(dates) if isinstance(dates, str) else dates
        collections = {
            "General": collections_raw.get("blackBinDay") or [],
            "Recycling": collections_raw.get("recyclingBinDay") or [],
            "Red Recycling": collections_raw.get("redRecyclingBinDay") or [],
            "Blue Recycling": collections_raw.get("blueRecyclingBinDay") or [],
            "Food": collections_raw.get("foodBinDay") or [],
            "Garden": collections_raw.get("gardenBinDay") or [],
        }

        return [
            Collection(datetime.strptime(day, "%Y-%m-%dT%H:%M:%S").date(), bin_type)
            for bin_type, days in collections.items()
            for day in days
        ]


SCRAPER = Canterbury()
