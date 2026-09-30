"""Hart District Council: looks up one year's collection dates by UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_URL = "https://www.hart.gov.uk/"


class Hart(Scraper):
    meta = Meta(
        title="Hart District Council",
        url=_URL,
        lads=("E07000089",),
        cases={
            "Test_001": {"uprn": "100060420702"},
            "Test_002": {"uprn": "100061994826"},
            "Test_003": {"uprn": "200003085501"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _URL + "bbd-whitespace/one-year-collection-dates",
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


SCRAPER = Hart()
