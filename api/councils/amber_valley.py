"""Amber Valley: fetches the council's waste collection JSON by UPRN."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from api.councils._base import Address, Collection, Http, Meta, Scraper

_ENDPOINT = (
    "https://info.ambervalley.gov.uk/WebServices/AVBCFeeds/"
    "WasteCollectionJSON.asmx/GetCollectionDetailsByUPRN"
)

_WASTE_TYPES_DATE_KEY = {
    "REFUSE": "refuseNextDate",
    "RECYCLING": "recyclingNextDate",
    "GREEN": "greenNextDate",
    "COMMUNAL REFUSE": "communalRefNextDate",
    "COMMUNAL RECYCLING": "communalRycNextDate",
}

_WASTE_TYPE_FREQUENCY_KEY = {
    "REFUSE": "weeklyCollection",
    "RECYCLING": "weeklyCollection",
    "GREEN": "weeklyCollection",
    "COMMUNAL REFUSE": "communalRefWeekly",
    "COMMUNAL RECYCLING": "communalRycWeekly",
}


def _get_date(date_string: str) -> date:
    return datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%S").date()


class AmberValley(Scraper):
    meta = Meta(
        title="Amber Valley Borough Council",
        url="https://ambervalley.gov.uk",
        lads=("E07000032",),
        cases={
            "Test_001": {"uprn": "100030011612", "predict": "true"},
            "Test_002": {"uprn": "100030011654"},
            "test_003": {"uprn": "100030041980", "predict": "true"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        predict = address.extra.get("predict", "").lower() == "true"
        r = await http.get(f"{_ENDPOINT}?uprn={uprn}")
        data: Mapping[str, Any] = r.json()

        collections = []
        for bin_type, date_key in _WASTE_TYPES_DATE_KEY.items():
            collection_date = _get_date(data[date_key])
            if collection_date == date(1900, 1, 1):
                continue

            collections.append(Collection(collection_date, bin_type))
            if predict:
                weekly = data[_WASTE_TYPE_FREQUENCY_KEY[bin_type]]
                day_offset = 7 if weekly else 14
                for i in range(1, 365 // day_offset):
                    collections.append(
                        Collection(
                            collection_date + timedelta(days=day_offset * i),
                            bin_type,
                        )
                    )

        return collections


SCRAPER = AmberValley()
