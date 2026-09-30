"""Falkirk: fetches collection dates directly from its API using the property's UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

API = "https://recycling.falkirk.gov.uk/api/collections"


class Falkirk(Scraper):
    meta = Meta(
        title="Falkirk",
        url="https://www.falkirk.gov.uk",
        lads=("S12000014",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{API}/{address.need('uprn')}")
        bin_collection = r.json()

        collections = []
        for collection in bin_collection["collections"]:
            bin_type = collection["type"]
            for day in collection["dates"]:
                collections.append(
                    Collection(datetime.strptime(day, "%Y-%m-%d").date(), bin_type)
                )
        return collections


SCRAPER = Falkirk()
