"""Stevenage: AchieveForms. A one-time token lookup precedes the collections lookup for the UPRN."""

from __future__ import annotations

import time
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError
from api.councils._platforms.achieveforms import init_session, run_lookup

_BASE_URL = "https://stevenage-self.achieveservice.com"
_TOKEN_URL = f"{_BASE_URL}/apibroker/runLookup?id=5e55337a540d4"
_LOOKUP_ID = "64ba8cee353e6"


class Stevenage(Scraper):
    meta = Meta(
        title="Stevenage Borough Council",
        url="https://www.stevenage.gov.uk/",
        lads=("E07000243",),
        cases={
            "Chepstow Close": {"uprn": "100080879233"},
            "Rectory Lane": {"uprn": "100081137566"},
            "Neptune Gate": {"uprn": "200000585910"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        sid = await init_session(
            http,
            f"{_BASE_URL}/en/service/Check_your_household_bin_collection_days",
            f"{_BASE_URL}/authapi/isauthenticated",
            "stevenage-self.achieveservice.com",
        )
        # Stevenage-specific: a one-time token before the main lookup.
        r = await http.get(_TOKEN_URL)
        token = r.json()["integration"]["transformed"]["rows_data"]["0"]["token"]

        result = await run_lookup(
            http,
            f"{_BASE_URL}/apibroker/runLookup",
            sid,
            _LOOKUP_ID,
            {
                "Section 1": {
                    "token": {"value": token},
                    "LLPGUPRN": {"value": address.need("uprn")},
                    "MinimumDateLookAhead": {"value": time.strftime("%Y-%m-%d")},
                    "MaximumDateLookAhead": {
                        "value": str(int(time.strftime("%Y")) + 1) + time.strftime("-%m-%d"),
                    },
                }
            },
        )
        rows_data = result["integration"]["transformed"]["rows_data"]
        if not isinstance(rows_data, dict):
            raise UpstreamError("Stevenage returned invalid data")

        collections = []
        for value in rows_data.values():
            try:
                day = datetime.strptime(value["collectiondate"], "%A %d %B %Y").date()
            except ValueError:
                continue
            collections.append(Collection(day, value["bintype"].strip()))
        return collections


SCRAPER = Stevenage()
