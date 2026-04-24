from datetime import datetime
from time import time_ns

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Gloucester City Council"
DESCRIPTION = "Source for gloucester.gov.uk waste collection."
URL = "https://www.gloucester.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "100120479507", "postcode": "GL2 0RR"},
}

HOST = "https://gloucester-self.achieveservice.com"
AUTH_URL = f"{HOST}/authapi/isauthenticated?uri=https%253A%252F%252Fgloucester-self.achieveservice.com%252Fservice%252FBins___Check_your_bin_day&hostname=gloucester-self.achieveservice.com&withCredentials=true"
API_URL = f"{HOST}/apibroker/runLookup"

# Lookup IDs from XHR capture
ADDRESS_LOOKUP_ID = "57fb9bf5aa4b8"
BIN_CONFIG_LOOKUP_ID = "63f72ddc8ca25"
DATE_LOOKUP_IDS = {
    "Household recycling (green box, brown food bin and blue sack)": "63cfcf4756b5d",
    "Food waste (brown food bin)": "63cfcf8ac7877",
    "Household waste (Domestic Waste Sack)": "640b1a2ad1e75",
}
DATE_LOOKUP_WEEK2 = {
    "Household waste (Domestic Waste Sack) Week 2": "6450dee4161c8",
}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}

ICON_MAP = {
    "HOUSEHOLD RECYCLING": "mdi:recycle",
    "FOOD WASTE": "mdi:food-apple",
    "HOUSEHOLD WASTE": "mdi:trash-can",
    "GARDEN WASTE": "mdi:leaf",
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


class Source:
    def __init__(self, uprn: str | int, postcode: str | None = None):
        self._uprn = str(uprn)
        self._postcode = postcode or ""

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as s:
            r = await s.get(AUTH_URL, headers=HEADERS)
            r.raise_for_status()
            sid = r.json()["auth-session"]

            form_state = {
                "Section 1": {
                    "chooseAddress": {"value": self._uprn},
                    "find_postcode": {"value": self._postcode},
                    "binUprn": {"value": self._uprn},
                }
            }

            # Step 1: bin config — get service IDs for this property
            r = await s.post(
                API_URL,
                headers=HEADERS,
                params=_params(BIN_CONFIG_LOOKUP_ID, sid),
                json={"formValues": form_state},
            )
            r.raise_for_status()
            _rows(r.json()).get("0", {})

            # Step 2: fetch next collection dates for each bin type
            entries = []
            for bin_type, lookup_id in DATE_LOOKUP_IDS.items():
                r = await s.post(
                    API_URL,
                    headers=HEADERS,
                    params=_params(lookup_id, sid),
                    json={"formValues": form_state},
                )
                r.raise_for_status()
                row = _rows(r.json()).get("0", {})
                for key, val in row.items():
                    if key.endswith("ISO") and "Next" in key and val:
                        try:
                            dt = datetime.strptime(val, "%Y-%m-%d").date()
                            first_words = " ".join(bin_type.split()[:2]).upper()
                            icon = ICON_MAP.get(first_words)
                            entries.append(Collection(date=dt, t=bin_type, icon=icon))
                        except ValueError:
                            continue

            # Step 3: week 2 refuse sack (alternate week)
            for bin_type, lookup_id in DATE_LOOKUP_WEEK2.items():
                r = await s.post(
                    API_URL,
                    headers=HEADERS,
                    params=_params(lookup_id, sid),
                    json={"formValues": form_state},
                )
                r.raise_for_status()
                row = _rows(r.json()).get("0", {})
                for key, val in row.items():
                    if key.endswith("ISO") and "Next" in key and val:
                        try:
                            dt = datetime.strptime(val, "%Y-%m-%d").date()
                            entries.append(
                                Collection(date=dt, t="Household waste (Domestic Waste Sack)", icon="mdi:trash-can")
                            )
                        except ValueError:
                            continue

        return sorted(entries, key=lambda c: c.date)
