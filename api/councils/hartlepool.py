"""Hartlepool: AchieveForms lookup keyed on the UPRN, answering with an HTML fragment."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    soup,
)
from api.councils._platforms.achieveforms import run_lookup

BASE = "https://online.hartlepool.gov.uk"


class Hartlepool(Scraper):
    meta = Meta(
        title="Hartlepool Borough Council",
        url="https://www.hartlepool.gov.uk",
        lads=("E06000001",),
        cases={
            "Test_001": {"uprn": "100110021946"},
            "Test_002": {"uprn": "100110007383"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        await http.get(f"{BASE}/apibroker/domain/online.hartlepool.gov.uk")
        auth = await http.get(
            f"{BASE}/authapi/isauthenticated",
            params={
                "uri": f"{BASE}/service/Refuse_and_recycling___check_bin_day",
                "hostname": "online.hartlepool.gov.uk",
                "withCredentials": "true",
            },
        )
        result = await run_lookup(
            http,
            f"{BASE}/apibroker/runLookup",
            auth.json()["auth-session"],
            "5ec67e019ffdd",
            {"Section 1": {"collectionLocationUPRN": {"value": address.need("uprn")}}},
            no_retry="true",
        )
        rows = result["integration"]["transformed"]["rows_data"]
        if "0" not in rows:
            raise InputError("Hartlepool has no bin schedule for this UPRN")

        collections = []
        for span in soup(rows["0"]["HTMLCollectionDatesText"]).select("div span"):
            # "... (Green) 06/10/2026"
            bin_type, day = span.get_text().split()[-2:]
            collections.append(
                Collection(datetime.strptime(day, "%d/%m/%Y").date(), bin_type.strip("()").capitalize())
            )
        return collections


SCRAPER = Hartlepool()
