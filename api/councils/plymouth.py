"""Plymouth: AchieveForms. A lookup returns a short-lived signed key, which a second lookup
uses to list the jobs for a UPRN inside a 60-day window."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper
from api.councils._platforms.achieveforms import init_session, run_lookup

_HOSTNAME = "plymouth-self.achieveservice.com"
_BASE_URL = f"https://{_HOSTNAME}"
_INITIAL_URL = (
    f"{_BASE_URL}/en/AchieveForms/?form_uri=sandbox-publish://AF-Process-084d6742-3572-41ba-ac1a-430750451f9d/"
    "AF-Stage-67ba684d-0a5b-48f8-9c50-1c01cc43c396/definition.json"
    "&redirectlink=%2Fen&cancelRedirectLink=%2Fen&consentMessage=yes"
)
_KEY_LOOKUP_ID = "6936e38f6d376"
_COLLECTIONS_LOOKUP_ID = "698b9c49a3c13"
_LOOKAHEAD_DAYS = 60

# Job name prefix -> the bin shown.
_COLLECTION_TYPE = {
    "Empty Residual": "Domestic Brown Bin",
    "Empty Recycling": "Recycling Green Bin",
    "Empty Food": "Food Waste Bin",
    "Empty Garden": "Garden Waste Bin",
}


def _rows(result: dict) -> list[dict]:
    rows_data = result["integration"]["transformed"]["rows_data"]
    if isinstance(rows_data, dict):
        return list(rows_data.values())
    return list(rows_data)


class Plymouth(Scraper):
    meta = Meta(
        title="Plymouth City Council",
        url="https://www.plymouth.gov.uk/",
        lads=("E06000026",),
        cases={
            "Test_001": {"uprn": "100040429524"},
            "Test_002": {"uprn": "100040425325"},
            "Test_003": {"uprn": "100040472543"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        api_url = f"{_BASE_URL}/apibroker/runLookup"
        sid = await init_session(
            http,
            _INITIAL_URL,
            f"{_BASE_URL}/authapi/isauthenticated",
            _HOSTNAME,
            auth_test_url=f"{_BASE_URL}/apibroker/domain/{_HOSTNAME}",
        )
        key_rows = _rows(await run_lookup(http, api_url, sid, _KEY_LOOKUP_ID, {"Section 1": {}}))
        if not key_rows:
            return []

        today = date.today()
        fmt = "%Y-%m-%dT00:00:00"
        jobs = _rows(
            await run_lookup(
                http,
                api_url,
                sid,
                _COLLECTIONS_LOOKUP_ID,
                {
                    "Section 1": {
                        "collectiveKey": {"value": key_rows[0]["collectiveKey"]},
                        "collectiveUPRN": {"value": address.need("uprn")},
                        "collectiveGetJobStartDate": {"value": today.strftime(fmt)},
                        "collectiveGetJobEndDate": {
                            "value": (today + timedelta(days=_LOOKAHEAD_DAYS)).strftime(fmt)
                        },
                    }
                },
            )
        )

        collections = []
        for job in jobs:
            waste_type = job["collectiveWasteType"]
            service = next((k for k in _COLLECTION_TYPE if waste_type.startswith(k)), None)
            if service is None:
                continue
            day = datetime.strptime(job["collectiveCollectionDate"], "%d/%m/%Y").date()
            collections.append(Collection(day, _COLLECTION_TYPE[service]))
        return collections


SCRAPER = Plymouth()
