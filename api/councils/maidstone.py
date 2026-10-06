"""Maidstone: an AchieveForms lookup keyed on the UPRN, returning collection dates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from api.councils._base import Address, AddressNotFound, Collection, Http, Meta, Scraper
from api.councils._platforms.achieveforms import init_session, rows, run_lookup

_HOSTNAME = "my.maidstone.gov.uk"
_BASE = f"https://{_HOSTNAME}"
_FORM_URI = f"{_BASE}/service/Find-your-bin-day"


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

        sid = await init_session(
            http,
            None,
            f"{_BASE}/authapi/isauthenticated",
            _HOSTNAME,
            uri=_FORM_URI,
            domain_url=f"{_BASE}/apibroker/domain/{_HOSTNAME}",
        )

        reply_rows = rows(
            await run_lookup(
                http,
                f"{_BASE}/apibroker/runLookup",
                sid,
                "654b7b6478deb",
                {"Lookup": {"AddressData": {"value": uprn}, "AddressUPRN": {"value": uprn}}},
                no_retry="true",
            )
        )
        rowdata = reply_rows.get(uprn)
        if rowdata is None:
            raise AddressNotFound(f"Maidstone has no collection data for UPRN {uprn}")

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
                collection.dates.append(datetime.strptime(value, "%d/%m/%Y").date())

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
