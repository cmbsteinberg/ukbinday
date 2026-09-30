"""South Gloucestershire: looks up next collections from the UPRN-based waste API."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API = "https://api.southglos.gov.uk/wastecomp/GetCollectionDetails"
_WASTE_MAP = {
    "Refuse": "BLACK BIN",
    "Recycling": "RECYCLING",
    "Garden": "GARDEN WASTE",
    "Food": "FOOD BIN",
    "AHP": "AHP BIN",
}


class SouthGloucestershire(Scraper):
    meta = Meta(
        title="South Gloucestershire Council",
        url="https://southglos.gov.uk",
        lads=("E06000025",),
        cases={
            "Test_001": {"uprn": "643346"},
            "Test_002": {"uprn": "641084"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{_API}?uprn={address.need('uprn')}")
        pickups = r.json()

        collections = []
        for item in pickups["value"]:
            next_collection = item.get("hso_nextcollection")
            if next_collection:
                collections.append(
                    Collection(
                        datetime.strptime(next_collection.split("T")[0], "%Y-%m-%d").date(),
                        _WASTE_MAP[item["hso_servicename"]],
                    )
                )
        return collections


SCRAPER = SouthGloucestershire()
