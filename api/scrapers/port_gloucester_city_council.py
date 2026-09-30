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

# Per bin type the chain is: bin-ids lookup -> workflow lookup (keyed on the id)
# -> next-date lookup (keyed on the workflow token).
BIN_CONFIG_LOOKUP_ID = "63f72ddc8ca25"
BIN_TYPES = {
    "Refuse": {
        "workflow_lookup_id": "63f731d2b50d7",
        "next_lookup_id": "63ca72c70c3b1",
        "label": "Household waste (black bin)",
        "icon": "mdi:trash-can",
    },
    "Recycling": {
        "workflow_lookup_id": "63f89f73018c0",
        "next_lookup_id": "63cfcf4756b5d",
        "label": "Recycling",
        "icon": "mdi:recycle",
    },
    "Food": {
        "workflow_lookup_id": "63f8a11714712",
        "next_lookup_id": "63cfcf8ac7877",
        "label": "Food waste",
        "icon": "mdi:food-apple",
    },
    "Garden": {
        "workflow_lookup_id": "63f8a15776b5d",
        "next_lookup_id": "63cfcfc1c486c",
        "label": "Garden waste",
        "icon": "mdi:leaf",
    },
}
SECTION = "Your waste collections"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
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

    async def _lookup(self, s: httpx.AsyncClient, sid: str, lookup_id: str, fields: dict) -> dict:
        r = await s.post(
            API_URL,
            headers=HEADERS,
            params=_params(lookup_id, sid),
            json={"formValues": {SECTION: fields}},
        )
        r.raise_for_status()
        return _rows(r.json()).get("0", {})

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as s:
            r = await s.get(AUTH_URL, headers=HEADERS)
            r.raise_for_status()
            sid = r.json()["auth-session"]

            ids = await self._lookup(s, sid, BIN_CONFIG_LOOKUP_ID, {"binUprn": {"value": self._uprn}})
            entries = []
            for bin_type, cfg in BIN_TYPES.items():
                id_field = f"{bin_type}Id"
                bin_id = ids.get(id_field)
                if not bin_id:
                    continue
                wf = await self._lookup(s, sid, cfg["workflow_lookup_id"], {id_field: {"value": bin_id}})
                token = wf.get(f"{bin_type}1")
                if not token:
                    continue
                nxt = await self._lookup(s, sid, cfg["next_lookup_id"], {f"{bin_type}1": {"value": token}})
                val = nxt.get(f"Next{bin_type}1DateISO")
                if not val:
                    continue
                try:
                    dt = datetime.strptime(val, "%Y-%m-%d").date()
                except ValueError:
                    continue
                entries.append(Collection(date=dt, t=cfg["label"], icon=cfg["icon"]))

        return sorted(entries, key=lambda c: c.date)
