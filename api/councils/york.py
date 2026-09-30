"""City of York: fetches the bin calendar JSON for a UPRN."""

from __future__ import annotations

import json
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

API = "https://waste-api.york.gov.uk/api/Collections/GetBinCalendarDataForUprn"


class York(Scraper):
    meta = Meta(
        title="City of York Council",
        url="https://york.gov.uk",
        lads=("E06000014",),
        cases={
            "Reighton Avenue, York": {"uprn": "100050580641"},
            "Granary Walk, York": {"uprn": "010093236548"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{API}/{address.need('uprn')}")
        data = json.loads(r.text)

        entries = []
        for collection in data["collections"]:
            try:
                entries.append(
                    Collection(
                        date=datetime.strptime(
                            collection["date"], "%Y-%m-%dT%H:%M:%S"
                        ).date(),
                        type=collection["roundType"].title(),
                    )
                )
            except ValueError:
                pass  # Ignore date conversion failures for unscheduled collections.

        return entries


SCRAPER = York()
