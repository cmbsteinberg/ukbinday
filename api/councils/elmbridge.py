"""Elmbridge: AchieveForms lookup by UPRN; each row is a date with up to three service columns."""

from __future__ import annotations

from dateutil.parser import parse

from api.councils._base import Address, Collection, Http, Meta, Scraper
from api.councils._platforms.achieveforms import init_session, run_lookup

_BASE_URL = "https://elmbridge-self.achieveservice.com"
_HOSTNAME = "elmbridge-self.achieveservice.com"


class Elmbridge(Scraper):
    meta = Meta(
        title="Elmbridge Borough Council",
        url="https://www.elmbridge.gov.uk",
        lads=("E07000207",),
        cases={
            "Test_001": {"uprn": "10013119164"},
            "Test_002": {"uprn": "100061309206"},
            "Test_003": {"uprn": "100062119825"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        sid = await init_session(
            http,
            f"{_BASE_URL}/service/Your_bin_collection_days",
            f"{_BASE_URL}/authapi/isauthenticated",
            _HOSTNAME,
            auth_test_url=f"{_BASE_URL}/apibroker/domain/{_HOSTNAME}",
        )
        result = await run_lookup(
            http,
            f"{_BASE_URL}/apibroker/runLookup",
            sid,
            "663b557cdaece",
            {"Section 1": {"UPRN": {"value": address.need("uprn")}}},
        )
        rows_data = result["integration"]["transformed"]["rows_data"]
        rows = list(rows_data.values()) if isinstance(rows_data, dict) else rows_data

        collections = []
        for row in rows:
            day = parse(row["Date"], dayfirst=True).date()
            for service in (row.get("Service1"), row.get("Service2"), row.get("Service3")):
                if not service:
                    continue
                collections.append(Collection(day, service.removesuffix(" Collection Service")))
        return collections


SCRAPER = Elmbridge()
