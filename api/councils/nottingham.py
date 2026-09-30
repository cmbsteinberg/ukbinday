"""Nottingham: looks up upcoming collections from the council's API by UPRN."""

from __future__ import annotations

import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_BINS = {
    "Recycling": "Recycling",
    "Waste": "General",
    "Garden": "Garden",
    "Food23L": "Food",
    "Food23L_bags": "Food",
}


class Nottingham(Scraper):
    meta = Meta(
        title="Nottingham City Council",
        url="https://nottinghamcity.gov.uk",
        lads=("E06000018",),
        cases={
            "Douglas Rd, Nottingham NG7 1NW": {"uprn": "100031540175"},
            "Harlaxton Drive, Nottingham, NG7 1JE": {"uprn": "100031553830"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            f"https://geoserver.nottinghamcity.gov.uk/bincollections2/api/collection/{address.need('uprn')}"
        )
        data = r.json()

        entries = []
        next_collections = data["nextCollections"]

        # Sometimes the API returns collections far in the future; only consider the next 12 months.
        for collection in next_collections:
            bin_type = collection["collectionType"]
            bin_name = _BINS[bin_type]
            next_collection_date = datetime.datetime.fromisoformat(collection["collectionDate"])

            if next_collection_date > datetime.datetime.now() + datetime.timedelta(days=365):
                continue

            entries.append(Collection(next_collection_date.date(), bin_name))

        return entries


SCRAPER = Nottingham()
