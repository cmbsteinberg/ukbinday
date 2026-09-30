"""Erewash: looks up a property's collection dates by UPRN via its Drupal AJAX endpoint."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

URL = "https://www.erewash.gov.uk/"
COLLECTION_DATES_URL = URL + "bbd-whitespace/one-year-collection-dates"


class Erewash(Scraper):
    meta = Meta(
        title="Erewash Borough Council",
        url=URL,
        lads=("E07000036",),
        cases={
            "Test_001": {"uprn": "100030126659"},
            "Test_002": {"uprn": "100030154311"},
            "Test_003": {"uprn": "100030118783"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            COLLECTION_DATES_URL,
            params={"uprn": address.need("uprn"), "_wrapper_format": "drupal_ajax"},
            timeout=30,
        )

        collections = []
        for _, data in r.json()[0]["settings"]["collection_dates"].items():
            for collection in data:
                collections.append(
                    Collection(
                        date=datetime.fromtimestamp(int(collection["timestamp"])).date(),
                        type=collection["service"],
                    )
                )
        return collections


SCRAPER = Erewash()
