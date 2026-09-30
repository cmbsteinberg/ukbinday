"""Maidstone: an AchieveForms lookup keyed on the UPRN, returning collection dates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from time import time_ns
from typing import Any

from api.councils._base import Address, Collection, Http, Meta, Scraper

_BASE = "https://my.maidstone.gov.uk"
_AUTH_URL = (
    "https://my.maidstone.gov.uk/authapi/isauthenticated"
    "?uri=https%3A%2F%2Fmy.maidstone.gov.uk%2Fservice%2FFind-your-bin-day"
    "&hostname=my.maidstone.gov.uk&withCredentials=true"
)
_SESSION_ID = "979631f89458fc974cc2aa69ebbd7996"


@dataclass
class _CollectionData:
    dates: list[date]
    description: str | None = None


class Maidstone(Scraper):
    meta = Meta(
        title="Maidstone Borough Council",
        url="https://maidstone.gov.uk",
        lads=("E07000110",),
        cases={
            "Test_001": {"uprn": "10022892379"},
            "Test_002": {"uprn": "10014307164"},
            "Test_003": {"uprn": "200003674881"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        timestamp = time_ns() // 1_000_000
        await http.get(f"{_BASE}/apibroker/domain/my.maidstone.gov.uk?_={timestamp}&sid={_SESSION_ID}")

        sid_request = await http.get(_AUTH_URL)
        sid = sid_request.json()["auth-session"]

        timestamp = time_ns() // 1_000_000
        payload = {
            "formValues": {
                "Lookup": {
                    "AddressData": {"value": uprn},
                    "AddressUPRN": {"value": uprn},
                }
            }
        }
        schedule_request = await http.post(
            f"{_BASE}/apibroker/runLookup"
            f"?id=654b7b6478deb&repeat_against=&noRetry=true&getOnlyTokens=undefined"
            f"&log_id=&app_name=AF-Renderer::Self&_={timestamp}&sid={sid}",
            json=payload,
        )

        try:
            rowdata: dict[str, Any] = schedule_request.json()["integration"]["transformed"]["rows_data"][uprn]
        except KeyError:
            return []

        collections: dict[str, _CollectionData] = {}

        for key, value in rowdata.items():
            collection_key = key.split("_")[0]
            active_key = f"{collection_key}_Active"
            if rowdata.get(active_key) == "N":
                continue

            if (
                key.endswith("_NextCollectionDateMM")
                and "Default" not in key
                and "Original" not in key
                and value != ""
            ):
                collection = collections.setdefault(collection_key, _CollectionData(dates=[]))
                try:
                    collection.dates.append(datetime.strptime(value, "%d/%m/%Y").date())
                except ValueError:
                    pass

            if "_Description" in key and "Default" not in key:
                collection = collections.setdefault(collection_key, _CollectionData(dates=[]))
                collection.description = value

        entries: list[Collection] = []
        for key, collection in collections.items():
            bin_name = collection.description or key
            for collection_date in collection.dates:
                entries.append(Collection(collection_date, bin_name))

        return entries


SCRAPER = Maidstone()
