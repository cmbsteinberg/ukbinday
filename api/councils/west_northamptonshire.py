"""West Northamptonshire: fetches collection dates from its unified waste collections API."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, Transport

API_URL = "https://api.westnorthants.digital/openapi/v1/unified-waste-collections/{uprn}"


class WestNorthamptonshire(Scraper):
    meta = Meta(
        title="West Northamptonshire council",
        url="https://www.westnorthants.gov.uk/",
        lads=("E06000062",),
        cases={
            "28058314": {"uprn": "28058314"},
            "15049111": {"uprn": "15049111"},
        },
    )
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(API_URL.format(uprn=address.need("uprn")))
        data = response.json()

        collections = []
        for collection in data["collectionItems"]:
            day = datetime.strptime(collection["date"], "%Y-%m-%d").date()
            collections.append(Collection(day, collection["type"]))

        return collections


SCRAPER = WestNorthamptonshire()
