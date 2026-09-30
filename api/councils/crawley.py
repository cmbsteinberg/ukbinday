"""Crawley (myCrawley): AchieveForms lookup keyed on UPRN and an optional USRN.

Based on the Elmbridge scraper. The reply is a list of rows whose
`<Type>DateCurrent` / `<Type>DateNext` keys hold the dates.
"""

from __future__ import annotations

from datetime import date, datetime

from dateutil.parser import parse

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)
from api.councils._platforms.achieveforms import init_session, run_lookup

_BASE_URL = "https://my.crawley.gov.uk"
_LOOKUP_ID = "5b4f0ec5f13f4"


class Crawley(Scraper):
    meta = Meta(
        title="Crawley Borough Council (myCrawley)",
        url="https://crawley.gov.uk/",
        lads=("E07000226",),
        cases={
            "Feroners Cl": {"uprn": "100061775179"},
            "Peterborough Road": {"uprn": "100061787552", "usrn": "9700731"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        sid = await init_session(
            http,
            f"{_BASE_URL}/en/service/check_my_bin_collection",
            f"{_BASE_URL}/authapi/isauthenticated",
            "elmbridge-self.achieveservice.com",
            auth_test_url=f"{_BASE_URL}/apibroker/domain/my.crawley.gov.uk",
        )
        result = await run_lookup(
            http,
            f"{_BASE_URL}/apibroker/runLookup",
            sid,
            _LOOKUP_ID,
            {
                "Address": {
                    "address": {
                        "value": {
                            "Address": {
                                "usrn": {"value": address.extra.get("usrn") or "0000"},
                                "uprn": {"value": uprn},
                            }
                        }
                    },
                    "dayConverted": {"value": datetime.now().strftime("%d/%m/%Y")},
                    "getCollection": {"value": "true"},
                    "getWorksheets": {"value": "false"},
                }
            },
        )
        rows = list(result["integration"]["transformed"]["rows_data"].values())

        collections: list[Collection] = []
        failed: list[str] = []
        for row in rows:
            for key in [k for k in row if k.endswith(("DateCurrent", "DateNext"))]:
                text = row[key]
                if not text:
                    continue
                day: date
                try:
                    day = parse(text, dayfirst=True).date()
                except ValueError:
                    failed.append(text)
                    continue
                collections.append(Collection(day, key.split("Date")[0]))

        if not collections:
            if failed:
                raise UpstreamError(f"Failed to parse dates: {', '.join(failed)}")
            raise AddressNotFound(f"No collections found for {uprn}")
        return collections


SCRAPER = Crawley()
