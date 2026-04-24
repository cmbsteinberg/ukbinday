from datetime import datetime
from time import time_ns

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Tendring District Council"
DESCRIPTION = "Source for tendring.gov.uk waste collection."
URL = "https://www.tendring.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "100090604247"},
}

HOST = "https://tendring-self.achieveservice.com"
AUTH_URL = f"{HOST}/authapi/isauthenticated?uri=https%253A%252F%252Ftendring-self.achieveservice.com%252Fen%252Fservice%252FRubbish_and_recycling_collection_days&hostname=tendring-self.achieveservice.com&withCredentials=true"
API_URL = f"{HOST}/apibroker/runLookup"
SCHEDULE_LOOKUP_ID = "6347acbadc425"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}

ICON_MAP = {
    "RESIDUAL": "mdi:trash-can",
    "RECYCLING": "mdi:recycle",
    "FOOD": "mdi:food-apple",
    "GARDEN": "mdi:leaf",
    "RED": "mdi:recycle",
    "GREEN": "mdi:recycle",
}


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = str(uprn)

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True) as s:
            r = await s.get(AUTH_URL, headers=HEADERS)
            r.raise_for_status()
            sid = r.json()["auth-session"]

            timestamp = time_ns() // 1_000_000
            payload = {
                "formValues": {
                    "Select address": {
                        "selectedUPRN": {"value": self._uprn},
                        "selectAddress": {"value": self._uprn},
                    }
                }
            }
            params = {
                "id": SCHEDULE_LOOKUP_ID,
                "repeat_against": "",
                "noRetry": "true",
                "getOnlyTokens": "undefined",
                "log_id": "",
                "app_name": "AF-Renderer::Self",
                "_": str(timestamp),
                "sid": sid,
            }

            r = await s.post(API_URL, headers=HEADERS, params=params, json=payload)
            r.raise_for_status()
            data = r.json()

        rows_data = data.get("integration", {}).get("transformed", {}).get("rows_data", {})
        if not rows_data:
            return []

        row = rows_data.get("0", {})
        entries = []
        date_fields = {
            "nextResidualCollection": "Residual waste",
            "nextRedCollection": "Red recycling box",
            "nextGreenCollection": "Green recycling box",
            "nextFoodCollection": "Food waste",
            "nextGardenCollection": "Garden waste",
        }

        for field, bin_type in date_fields.items():
            date_str = row.get(field)
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str.split()[0], "%d/%m/%Y").date()
                first_word = bin_type.split()[0].upper()
                icon = ICON_MAP.get(first_word)
                entries.append(Collection(date=dt, t=bin_type, icon=icon))
            except (ValueError, IndexError):
                continue

        return sorted(entries, key=lambda c: c.date)
