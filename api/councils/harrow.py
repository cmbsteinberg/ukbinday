"""Harrow: looks up upcoming collections from its bins API using a padded UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
)

_API_URL = "https://www.harrow.gov.uk/ajax/bins?u={uprn}"
_COLLECTION_TYPES = {
    "RESIDUAL": "General waste",
    "GARDEN": "Garden waste",
    "RECYCLABLES": "Recycling waste",
    "FOOD": "Food waste",
}


class Harrow(Scraper):
    meta = Meta(
        title="London Borough of Harrow",
        url="https://www.harrow.gov.uk/",
        lads=("E09000015",),
        cases={
            "1 Dudley Gardens": {"uprn": "100021261713"},
            "FLAT 3, 12, LOWER ROAD, HARROW, HA2 0DA": {"uprn": "10070270427"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        response = await http.get(_API_URL.format(uprn=uprn))
        if not response.content:
            raise UpstreamError(
                f"No data returned for UPRN {uprn} — the service may be temporarily unavailable"
            )

        rubbish_data = response.json()
        collections = []
        for next_collection in rubbish_data["results"]["collections"]["next"]:
            collection_type = _COLLECTION_TYPES.get(next_collection["binType"])
            if collection_type is None:
                continue
            collection_date = next_collection["eventTime"]
            collections.append(
                Collection(
                    date=datetime.fromisoformat(collection_date).date(),
                    type=collection_type,
                )
            )

        return collections


SCRAPER = Harrow()
