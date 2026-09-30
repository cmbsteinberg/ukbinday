"""Havering: looks up upcoming collections from its API using a 12-digit UPRN."""

from __future__ import annotations

import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://api-prd.havering.gov.uk/whitespace/GetCollectionByUprnAndDate"

_COLLECTION_MAP = {
    "Service - Domestic Waste": "Domestic Waste",
    "Service - Garden Waste": "Garden Waste",
    "Service - Recycling": "Recycling",
    "Service - Garden Waste Winter": "Garden Waste Winter",
}


class Havering(Scraper):
    meta = Meta(
        title="London Borough of Havering",
        url="https://www.havering.gov.uk/",
        lads=("E09000016",),
        cases={"53 Argyle Gardens": {"uprn": "100021403735"}},
    )
    requires = frozenset({"uprn"})
    headers = {
        "Content-Type": "application/json",
        "Ocp-Apim-Trace": "true",
        "Ocp-Apim-Subscription-Key": "545bcf53c9094dfd980dd9da72b0514d",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        payload = {
            "getCollectionByUprnAndDate": {
                "getCollectionByUprnAndDateInput": {
                    "uprn": address.need("uprn").zfill(12),
                    "nextCollectionFromDate": datetime.datetime.today().strftime("%Y/%m/%d"),
                }
            }
        }
        response = await http.post(_API_URL, json=payload)
        data = response.json()

        entries = []
        for next_collection in data["getCollectionByUprnAndDateResponse"][
            "getCollectionByUprnAndDateResult"
        ]["Collections"]:
            service = next_collection["service"]
            collection_type = _COLLECTION_MAP.get(service, service)
            collection_date = next_collection["date"]
            entries.append(
                Collection(
                    date=datetime.datetime.strptime(collection_date, "%d/%m/%Y %H:%M:%S").date(),
                    type=collection_type,
                )
            )

        return entries


SCRAPER = Havering()
