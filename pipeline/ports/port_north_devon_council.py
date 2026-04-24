import asyncio
from datetime import datetime
from time import time_ns

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "North Devon Council"
DESCRIPTION = "Source for northdevon.gov.uk waste collection."
URL = "https://www.northdevon.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "100040249471", "postcode": "EX31 2LE"},
}

HOST = "https://my.northdevon.gov.uk"
AUTH_URL = f"{HOST}/authapi/isauthenticated?uri=https%253A%252F%252Fmy.northdevon.gov.uk%252Fservice%252FWasteRecyclingCollectionCalendar&hostname=my.northdevon.gov.uk&withCredentials=true"
API_URL = f"{HOST}/apibroker/runLookup"

USRN_LOOKUP_ID = "65141c7c38bd0"
TOKEN_LOOKUP_ID = "59e606ee95b7a"
DATE_RANGE_LOOKUP_ID = "6255925ca44cb"
SCHEDULE_LOOKUP_ID = "610943652e64f"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}

ICON_MAP = {
    "Black Bin": "mdi:trash-can",
    "Green Bin": "mdi:leaf",
    "Recycling": "mdi:recycle",
    "Food": "mdi:food-apple",
    "Brown Bag": "mdi:recycle",
}


def _params(lookup_id: str, sid: str, **extra) -> dict:
    return {
        "id": lookup_id,
        "repeat_against": "",
        "noRetry": extra.get("noRetry", "true"),
        "getOnlyTokens": "undefined",
        "log_id": "",
        "app_name": "AF-Renderer::Self",
        "_": str(time_ns() // 1_000_000),
        "sid": sid,
    }


def _rows(resp_json: dict) -> dict:
    return resp_json.get("integration", {}).get("transformed", {}).get("rows_data", {})


def _parse_schedule_html(html: str) -> list[Collection]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    current_month = None
    current_year = None

    for li in soup.find_all("li"):
        if "MonthLabel" in li.get("class", []):
            h4 = li.find("h4")
            if h4 and h4.text.strip() != "Key":
                parts = h4.text.strip().split()
                if len(parts) == 2:
                    current_month = parts[0]
                    current_year = int(parts[1])
            continue

        if not current_month or not current_year:
            continue

        day_span = li.find("span", class_="wasteDay")
        type_span = li.find("span", class_="wasteType")
        if not day_span or not type_span:
            continue

        day = day_span.text.strip()
        bin_type = type_span.text.strip()
        try:
            dt = datetime.strptime(f"{day} {current_month} {current_year}", "%d %B %Y").date()
        except ValueError:
            continue

        icon = None
        for key, val in ICON_MAP.items():
            if key.lower() in bin_type.lower():
                icon = val
                break

        entries.append(Collection(date=dt, t=bin_type, icon=icon))

    return entries


class Source:
    def __init__(self, uprn: str | int, postcode: str | None = None):
        self._uprn = str(uprn)
        self._postcode = postcode or ""

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as s:
            r = await s.get(AUTH_URL, headers=HEADERS)
            r.raise_for_status()
            sid = r.json()["auth-session"]

            base_form = {
                "Your address": {
                    "qsUPRN": {"value": self._uprn},
                    "selectedUPRN": {"value": self._uprn},
                }
            }

            # Step 1: get USRN
            r = await s.post(
                API_URL,
                headers=HEADERS,
                params=_params(USRN_LOOKUP_ID, sid),
                json={"formValues": base_form},
            )
            r.raise_for_status()
            usrn_row = _rows(r.json()).get("0", {})
            usrn = usrn_row.get("USRN", "")

            # Step 2: get live token
            r = await s.post(
                API_URL,
                headers=HEADERS,
                params=_params(TOKEN_LOOKUP_ID, sid),
                json={"formValues": base_form},
            )
            r.raise_for_status()
            token_row = _rows(r.json()).get("0", {})
            token = token_row.get("liveToken", "")

            # Step 3: get date range
            r = await s.post(
                API_URL,
                headers=HEADERS,
                params=_params(DATE_RANGE_LOOKUP_ID, sid),
                json={"formValues": base_form},
            )
            r.raise_for_status()
            date_row = _rows(r.json()).get("0", {})
            cal_start = date_row.get("calstartDate", "")
            cal_end = date_row.get("calendDate", "")

            # Step 4: get schedule HTML (may need two calls — first triggers, second retrieves)
            schedule_form = {
                "Your address": {
                    "qsUPRN": {"value": self._uprn},
                    "selectedUPRN": {"value": self._uprn},
                    "USRN": {"value": usrn},
                    "liveToken": {"value": token},
                    "calstartDate": {"value": cal_start},
                    "calendDate": {"value": cal_end},
                }
            }

            for _ in range(3):
                r = await s.post(
                    API_URL,
                    headers=HEADERS,
                    params=_params(SCHEDULE_LOOKUP_ID, sid, noRetry="true"),
                    json={"formValues": schedule_form},
                )
                r.raise_for_status()
                row = _rows(r.json()).get("0", {})
                results_html = row.get("Results2", "")
                if results_html and "<h3>" in results_html:
                    break
                await asyncio.sleep(2)

        if not results_html or "<h3>" not in results_html:
            return []

        entries = _parse_schedule_html(results_html)
        return sorted(entries, key=lambda c: c.date)
