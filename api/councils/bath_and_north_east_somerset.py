"""Bath & North East Somerset: resolve a postcode and address to a UPRN, then fetch its collection summary."""

from __future__ import annotations

from collections.abc import Mapping
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
    UpstreamError,
    match_address,
)

_API_BASE_URL = "https://api.bathnes.gov.uk/webapi/api/{}"
_API_COLLECTION_SUMMARY_URL = _API_BASE_URL.format(
    "BinsAPI/v2/BartecFeaturesandSchedules/CollectionSummary/{uprn}"
)
_API_ADDRESSES_SEARCH_URL = _API_BASE_URL.format(
    "AddressesAPI/v2/search/{postcode}/150/true"
)
_REQUEST_TIMEOUT = 10
_TYPES = {
    "Residual": "Rubbish",
    "Recycling": "Recycling",
    "Garden": "Garden Waste",
}


def _address_housenameornumber(address: Mapping[str, Any]) -> str | None:
    parts = str(address.get("payment_Address", "")).split("|")
    if len(parts) < 2:
        return None
    return parts[1].strip()


async def _call_api(http: Http, url: str) -> Any:
    response = await http.get(url, timeout=_REQUEST_TIMEOUT)
    if response.text.strip() == "":
        raise UpstreamError(f"Empty response from API for url: {url}")
    return response.json()


class BathAndNorthEastSomerset(Scraper):
    meta = Meta(
        title="Bath & North East Somerset Council",
        url="https://bathnes.gov.uk",
        lads=("E06000022",),
        cases={
            "uprn": {"uprn": "10001138699"},
            "houseNumber": {"postcode": "BA1 2LR", "house_number": "1"},
            "houseName": {"postcode": "BA1 5SX", "house_number": "St Stephen's Church"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if address.uprn is not None:
            uprn = int(address.uprn)
        else:
            if address.postcode is None or address.house_number is None:
                raise InputError(
                    "Postcode and house name or number are required if UPRN is not provided"
                )

            addresses = await _call_api(
                http,
                _API_ADDRESSES_SEARCH_URL.format(postcode=address.postcode),
            )
            if not addresses:
                raise AddressNotFound(f"No addresses for postcode {address.postcode}")

            candidates = [
                candidate
                for candidate in addresses
                if _address_housenameornumber(candidate) is not None
            ]
            selected = match_address(
                address,
                candidates,
                text=lambda candidate: _address_housenameornumber(candidate) or "",
                uprn=lambda candidate: candidate.get("uprn"),
            )
            uprn = int(selected["uprn"])

        entries = await _call_api(
            http,
            _API_COLLECTION_SUMMARY_URL.format(uprn=uprn),
        )
        return [
            Collection(datetime.fromisoformat(isodate).date(), alias)
            for entry in entries
            if (alias := _TYPES.get(entry.get("featureType")))
            for date_type in ("previous", "next")
            if (isodate := entry.get(f"{date_type}CollectionDate"))
        ]


SCRAPER = BathAndNorthEastSomerset()
