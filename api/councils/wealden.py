"""Wealden: POST a UPRN to the council's WordPress endpoint for collection dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, Transport

_API_URL = "https://www.wealden.gov.uk/wp-admin/admin-ajax.php"
_COLLECTIONS = {
    "refuseCollectionDate": "Rubbish",
    "recyclingCollectionDate": "Recycling",
    "gardenCollectionDate": "Garden",
    "foodCollectionDate": "Food",
}


class Wealden(Scraper):
    meta = Meta(
        title="Wealden District Council",
        url="https://www.wealden.gov.uk",
        lads=("E07000065",),
        cases={
            "Test_001": {"uprn": "10094620272"},
            "Test_002": {"uprn": "200001678582"},
            "Test_003": {"uprn": "100060120819"},
        },
    )
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36 Edg/113.0.1774.57",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": "https://wealden.gov.uk",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "Windows",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-requested-with": "XMLHttpRequest",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(
            _API_URL,
            data={
                "action": "wealden_get_collections_for_uprn",
                "uprn": address.need("uprn"),
            },
        )
        json_data = r.json()["collection"]
        collections = []

        for collection, bin_type in _COLLECTIONS.items():
            if not json_data[collection]:
                continue  # no date for this service
            collections.append(
                Collection(
                    datetime.strptime(json_data[collection], "%Y-%m-%dT%H:%M:%S").date(),
                    type=bin_type.title(),
                )
            )

        return collections


SCRAPER = Wealden()
