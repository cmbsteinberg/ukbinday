from datetime import date, datetime, timedelta

import httpx

from api.compat.hacs import Collection, Icons
from api.compat.hacs.service.AchieveForms import init_session, run_lookup

TITLE = "Plymouth City Council"
DESCRIPTION = "Source for waste collection services for Plymouth City Council"
URL = "https://www.plymouth.gov.uk/"

TEST_CASES = {
    "Test_001": {"uprn": 100040429524},
    "Test_002": {"uprn": "100040425325"},
    "Test_003": {"uprn": 100040472543},
    "Test_004": {"uprn": "100040462838"},
    "Test_005": {"uprn": 100040461084},
}

FORM_ID = "5c99439d85f83"
HOSTNAME = "plymouth-self.achieveservice.com"
BASE_URL = f"https://{HOSTNAME}"
INITIAL_URL = f"{BASE_URL}/en/AchieveForms/?form_uri=sandbox-publish://AF-Process-084d6742-3572-41ba-ac1a-430750451f9d/AF-Stage-67ba684d-0a5b-48f8-9c50-1c01cc43c396/definition.json&redirectlink=%2Fen&cancelRedirectLink=%2Fen&consentMessage=yes"
AUTH_URL = f"{BASE_URL}/authapi/isauthenticated"
AUTH_TEST = f"{BASE_URL}/apibroker/domain/{HOSTNAME}"
API_URL = f"{BASE_URL}/apibroker/runLookup"

# The form first fetches a short-lived signed key, then looks up the jobs for a
# UPRN inside a date window using that key.
KEY_LOOKUP_ID = "6936e38f6d376"
COLLECTIONS_LOOKUP_ID = "698b9c49a3c13"
LOOKAHEAD_DAYS = 60

ICON_MAP = {
    "Empty Residual": Icons.GENERAL_WASTE,
    "Empty Recycling": Icons.RECYCLING,
    "Empty Food": Icons.BIO_KITCHEN,
    "Empty Garden": Icons.GARDEN,
}

COLLECTION_TYPE = {
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


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = str(uprn).strip()

    async def get_collections(
        self, session_key: str, session: httpx.AsyncClient
    ) -> list[dict]:
        key_rows = _rows(
            await run_lookup(
                session, API_URL, session_key, KEY_LOOKUP_ID, {"Section 1": {}}
            )
        )
        if not key_rows:
            return []
        today = date.today()
        fmt = "%Y-%m-%dT00:00:00"
        return _rows(
            await run_lookup(
                session,
                API_URL,
                session_key,
                COLLECTIONS_LOOKUP_ID,
                {
                    "Section 1": {
                        "collectiveKey": {"value": key_rows[0]["collectiveKey"]},
                        "collectiveUPRN": {"value": self._uprn},
                        "collectiveGetJobStartDate": {"value": today.strftime(fmt)},
                        "collectiveGetJobEndDate": {
                            "value": (today + timedelta(days=LOOKAHEAD_DAYS)).strftime(
                                fmt
                            )
                        },
                    }
                },
            )
        )

    async def fetch(self) -> list[Collection]:
        session = httpx.AsyncClient(follow_redirects=True)
        session_key = await init_session(
            session,
            INITIAL_URL,
            AUTH_URL,
            HOSTNAME,
            auth_test_url=AUTH_TEST,
        )
        collections = await self.get_collections(session_key, session)

        entries = []
        seen = set()
        for collection in collections:
            waste_type = collection["collectiveWasteType"]
            service = next(
                (k for k in COLLECTION_TYPE if waste_type.startswith(k)), None
            )
            if service is None:
                continue
            date_obj = datetime.strptime(
                collection["collectiveCollectionDate"], "%d/%m/%Y"
            ).date()
            if (date_obj, service) in seen:
                continue
            seen.add((date_obj, service))
            entries.append(
                Collection(
                    date=date_obj,
                    t=COLLECTION_TYPE[service],
                    icon=ICON_MAP[service],
                )
            )

        return entries
