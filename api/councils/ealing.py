"""Ealing: submits the UPRN to its waste collection service and parses the returned dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://www.ealing.gov.uk/site/custom_scripts/WasteCollectionWS/home/FindCollection"


class Ealing(Scraper):
    meta = Meta(
        title="Ealing Council",
        url="https://www.ealing.gov.uk",
        lads=("E09000009",),
        cases={
            "11 LOTHAIR ROAD, EALING, LONDON, W5 4TA": {"uprn": "12081500"},
            "53 CREIGHTON ROAD, EALING, LONDON, W5 4SH": {"uprn": "12082293"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(_API_URL, data={"UPRN": address.need("uprn")})
        data = r.json()

        collections = []
        for entry in data["param2"]:
            bin_type = entry["Service"]
            for date_str in entry["collectionDate"]:
                day = datetime.strptime(date_str, "%d/%m/%Y").date()
                collections.append(Collection(date=day, type=bin_type))

        return collections


SCRAPER = Ealing()
