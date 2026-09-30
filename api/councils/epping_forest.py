"""Epping Forest: AchieveForms lookup by UPRN returning one row with a name and next date per service."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, AddressNotFound, Collection, Http, Meta, Scraper
from api.councils._platforms.achieveforms import init_session, run_lookup

_BASE_URL = "https://eppingforestdc-self.achieveservice.com"
_LOOKUP_COLLECTIONS = "6651dfb99a74d"

# (name field, next-collection field) per service.
_SERVICES = [
    ("FoodWasteServiceName", "FoodWasteServiceNextCollection"),
    ("FoodGardenServiceName", "FoodGardenServiceNextCollection"),
    ("GardenWasteServiceName", "GardenWasteServiceNextCollection"),
    ("RecyclingServiceName", "RecyclingServiceNextCollection"),
    ("GeneralWasteServiceName", "GeneralWasteServiceNextCollection"),
]


class EppingForest(Scraper):
    meta = Meta(
        title="Epping Forest District Council",
        url="https://www.eppingforestdc.gov.uk",
        lads=("E07000072",),
        cases={
            "51 Crows Road Epping": {"uprn": "100090495060"},
            "47 Crows Road Epping": {"uprn": "100090495056"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        sid = await init_session(
            http,
            f"{_BASE_URL}/en/service/Check_your_collection_day",
            f"{_BASE_URL}/authapi/isauthenticated",
            "eppingforestdc-self.achieveservice.com",
        )
        result = await run_lookup(
            http,
            f"{_BASE_URL}/apibroker/runLookup",
            sid,
            _LOOKUP_COLLECTIONS,
            {"Address": {"LookupUPRN": {"value": uprn}}},
        )
        rows = result.get("integration", {}).get("transformed", {}).get("rows_data", {})
        row = rows.get("0", {})

        collections = []
        for name_field, date_field in _SERVICES:
            name = row.get(name_field, "")
            text = row.get(date_field, "")
            if not name or not text:
                continue
            try:
                day = datetime.fromisoformat(text[:10]).date()
            except ValueError:
                continue
            # A sentinel date means the service has no next collection.
            if day.year < 2000:
                continue
            collections.append(Collection(day, name))

        if not collections:
            raise AddressNotFound(f"Epping Forest has no collections for UPRN {uprn}")
        return collections


SCRAPER = EppingForest()
