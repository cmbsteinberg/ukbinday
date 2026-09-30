"""North Lincolnshire: fetches bin collections from its UPRN-keyed JSON endpoint."""

from __future__ import annotations

import json
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper


class NorthLincolnshire(Scraper):
    meta = Meta(
        title="North Lincolnshire Council",
        url="https://www.northlincs.gov.uk",
        lads=("E06000013",),
        cases={
            "Test_001": {"uprn": "100050200824"},
            "Test_002": {"uprn": "100050188326"},
            "Test_003": {"uprn": "100050199446"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        r = await http.get(
            f"https://m.northlincs.gov.uk/bin_collections?no_collections=20&uprn={uprn}"
        )
        r_json = json.loads(r.content.decode("utf-8-sig"))["Collections"]

        entries = []
        for collection in r_json:
            day = datetime.strptime(
                collection["CollectionDate"].split(" ")[0], "%Y-%m-%d"
            ).date()
            waste_type = collection["BinCodeDescription"]
            entries.append(Collection(date=day, type=waste_type))
        return entries


SCRAPER = NorthLincolnshire()
