"""Tunbridge Wells: AchieveForms lookup keyed on the UPRN, returning upcoming collection dates."""

from __future__ import annotations

from datetime import datetime
from time import time_ns

from api.councils._base import Address, Collection, Http, Meta, Scraper

_HEADERS = {"user-agent": "Mozilla/5.0"}
_AUTH_URL = (
    "https://mytwbc.tunbridgewells.gov.uk/authapi/isauthenticated"
    "?uri=https%3A%2F%2Fmytwbc.tunbridgewells.gov.uk%2FAchieveForms%2F%3Fmode%3Dfill%26consentMessage%3Dyes%26form_uri%3Dsandbox-publish%3A%2F%2FAF-Process-e01af4d4-eb0f-4cfe-a5ac-c47b63f017ed%2FAF-Stage-88caf66c-378f-4082-ad1d-07b7a850af38%2Fdefinition.json%26process%3D1%26process_uri%3Dsandbox-processes%3A%2F%2FAF-Process-e01af4d4-eb0f-4cfe-a5ac-c47b63f017ed%26process_id%3DAF-Process-e01af4d4-eb0f-4cfe-a5ac-c47b63f017ed&hostname=mytwbc.tunbridgewells.gov.uk&withCredentials=true"
)
_LOOKUP_URL = "https://mytwbc.tunbridgewells.gov.uk/apibroker/runLookup"


class TunbridgeWells(Scraper):
    meta = Meta(
        title="Tunbridge Wells",
        url="https://tunbridgewells.gov.uk/",
        lads=("E07000116",),
        cases={
            "10090058289": {"uprn": "10090058289"},
            "100061204678": {"uprn": "100061204678"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        sid_response = await http.get(_AUTH_URL)
        sid = sid_response.json()["auth-session"]

        timestamp = time_ns() // 1_000_000
        payload = {
            "formValues": {
                "Property": {
                    key: {"value": address.need("uprn")}
                    for key in ("addressPicker", "propertyReference", "siteReference")
                }
            }
        }
        schedule_response = await http.post(
            f"{_LOOKUP_URL}?id=6314720683f30&repeat_against=&noRetry=false"
            f"&getOnlyTokens=undefined&log_id=&app_name=AF-Renderer::Self"
            f"&_={timestamp}&sid={sid}",
            json=payload,
        )
        rowdata = schedule_response.json()["integration"]["transformed"]["rows_data"]

        collections = []
        for item in rowdata.values():
            collections.append(
                Collection(
                    datetime.strptime(item["nextDateUnformatted"], "%d/%m/%Y").date(),
                    item["collectionType"],
                )
            )
        return collections


SCRAPER = TunbridgeWells()
