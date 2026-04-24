from datetime import datetime
from time import time_ns

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Three Rivers District Council"
DESCRIPTION = "Source for threerivers.gov.uk waste collection."
URL = "https://www.threerivers.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "100080913662"},
}

HOST = "https://my.threerivers.gov.uk"
AUTH_URL = f"{HOST}/authapi/isauthenticated?uri=https%253A%252F%252Fmy.threerivers.gov.uk%252Fen%252FAchieveForms%252F%253Fmode%253Dfill%2526consentMessage%253Dyes%2526form_uri%253Dsandbox-publish%253A%252F%252FAF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b%252FAF-Stage-01ee28aa-1584-442c-8d1f-119b6e27114a%252Fdefinition.json%2526process%253D1%2526process_uri%253Dsandbox-processes%253A%252F%252FAF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b%2526process_id%253DAF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b%2526noLoginPrompt%253D1&hostname=my.threerivers.gov.uk&withCredentials=true"
API_URL = f"{HOST}/apibroker/"
TOKEN_LOOKUP_ID = "58986058d4be0"
SCHEDULE_LOOKUP_ID = "58ac332f9e831"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}

ICON_MAP = {
    "REFUSE": "mdi:trash-can",
    "RECYCLING": "mdi:recycle",
    "GARDEN": "mdi:leaf",
    "FOOD": "mdi:food-apple",
}


def _api_params(lookup_id: str, sid: str, **extra) -> dict:
    return {
        "api": "RunLookup",
        "id": lookup_id,
        "repeat_against": "",
        "noRetry": extra.get("noRetry", "true"),
        "getOnlyTokens": "undefined",
        "log_id": "",
        "app_name": "AF-Renderer::Self",
        "_": str(time_ns() // 1_000_000),
        "sid": sid,
    }


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = str(uprn)

    async def fetch(self) -> list[Collection]:
        now = datetime.now()
        async with httpx.AsyncClient(follow_redirects=True) as s:
            r = await s.get(AUTH_URL, headers=HEADERS)
            r.raise_for_status()
            sid = r.json()["auth-session"]

            base_form = {
                "Your address details": {
                    "UPRN": {"value": self._uprn},
                    "todaysdate": {"value": now.strftime("%Y-%m-%dT00:00:00")},
                }
            }

            # Step 1: get token
            r = await s.post(
                API_URL,
                headers=HEADERS,
                params=_api_params(TOKEN_LOOKUP_ID, sid),
                json={"formValues": base_form},
            )
            r.raise_for_status()
            token_data = r.json()
            token = (
                token_data.get("integration", {})
                .get("transformed", {})
                .get("rows_data", {})
                .get("0", {})
                .get("token", "")
            )

            # Step 2: get schedule
            schedule_form = {
                "Your address details": {
                    "UPRN": {"value": self._uprn},
                    "todaysdate": {"value": now.strftime("%Y-%m-%dT00:00:00")},
                },
                "Your collection dates": {
                    "token": {"value": token},
                },
            }
            r = await s.post(
                API_URL,
                headers=HEADERS,
                params=_api_params(SCHEDULE_LOOKUP_ID, sid, noRetry="false"),
                json={"formValues": schedule_form},
            )
            r.raise_for_status()
            data = r.json()

        rows_data = data.get("integration", {}).get("transformed", {}).get("rows_data", {})
        if not rows_data:
            return []

        entries = []
        for _, row in rows_data.items():
            job_name = row.get("JobName", "")
            date_str = row.get("Date", "")
            if not job_name or not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%d-%m-%Y").date()
            except ValueError:
                continue
            first_word = job_name.split()[0].upper() if job_name else ""
            icon = ICON_MAP.get(first_word)
            entries.append(Collection(date=dt, t=job_name, icon=icon))

        return sorted(entries, key=lambda c: c.date)
