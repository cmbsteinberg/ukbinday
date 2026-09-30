import re
from datetime import date, datetime, timedelta
from time import time_ns
from xml.etree import ElementTree

import httpx

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
SERVICE_DETAILS_LOOKUP_ID = "61091d927cd81"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}

ICON_MAP = {
    "Black Bin": "mdi:trash-can",
    "Clinical": "mdi:trash-can",
    "Green Bin": "mdi:leaf",
    "Caddy": "mdi:food-apple",
    "Food": "mdi:food-apple",
    "Brown Bag": "mdi:recycle",
    "Blue Box": "mdi:recycle",
    "Black Box": "mdi:recycle",
    "Green Bag": "mdi:recycle",
    "Recycling": "mdi:recycle",
}


def _params(lookup_id: str, sid: str, no_retry: str = "true") -> dict:
    return {
        "id": lookup_id,
        "repeat_against": "",
        "noRetry": no_retry,
        "getOnlyTokens": "undefined",
        "log_id": "",
        "app_name": "AF-Renderer::Self",
        "_": str(time_ns() // 1_000_000),
        "sid": sid,
    }


def _rows(resp_json: dict) -> dict:
    rows = resp_json.get("integration", {}).get("transformed", {}).get("rows_data", {})
    return rows if isinstance(rows, dict) else {}


def _service_details(resp_json: dict) -> list[str]:
    """Extract ServiceDetail strings (e.g. 'Empty Bin Green Bin/05/09/2026')
    from the service-details lookup's raw XML payload."""
    details: list[str] = []
    try:
        root = ElementTree.fromstring(resp_json.get("data") or "<Responses/>")
    except ElementTree.ParseError:
        root = None
    if root is not None:
        for result in root.iter("result"):
            if result.get("column") == "ServiceDetail" and result.text:
                details.append(result.text.strip())
        if details:
            return details
    # Fallback: regex over the raw payload.
    data = resp_json.get("data") or ""
    return [
        m.strip()
        for m in re.findall(r'column="ServiceDetail"[^>]*>(.*?)</result>', data)
        if m.strip()
    ]


def _icon_for(bin_type: str) -> str | None:
    lowered = bin_type.lower()
    for key, icon in ICON_MAP.items():
        if key.lower() in lowered:
            return icon
    return None


def _parse_service_detail(text: str) -> Collection | None:
    detail = text.strip()
    if detail.lower().startswith("empty bin "):
        detail = detail[len("empty bin ") :]
    try:
        bin_type, day, month, year = detail.rsplit("/", 3)
    except ValueError:
        return None
    bin_type = bin_type.strip()
    if not bin_type:
        return None
    try:
        dt = datetime(int(year), int(month), int(day)).date()
    except ValueError:
        return None
    return Collection(date=dt, t=bin_type, icon=_icon_for(bin_type))


class Source:
    def __init__(self, uprn: str | int, postcode: str | None = None):
        self._uprn = str(uprn)
        self._postcode = (postcode or "").replace(" ", "")

    async def fetch(self) -> list[Collection]:
        today = date.today()
        form = {
            "Your address": {
                "qsUPRN": {"value": self._uprn},
                "postcode_search": {"value": self._postcode},
                "chooseAddress": {"value": self._uprn},
                "uprnfromlookup": {"value": self._uprn},
                "UPRNMF": {"value": self._uprn},
                "FULLADDR2": {"value": ""},
            },
            "Calendar": {
                "FULLADDR": {"value": ""},
                "token": {"value": ""},
                "uPRN": {"value": self._uprn},
                "calstartDate": {"value": ""},
                "calendDate": {"value": ""},
                "UPRN": {"value": self._uprn},
                "liveToken": {"value": ""},
                "USRN": {"value": ""},
                "StartDate": {"value": (today - timedelta(days=31)).isoformat()},
                "EndDate": {"value": (today + timedelta(days=1)).isoformat()},
            },
            "Print version": {"OutText2": {"value": ""}},
        }
        address = form["Your address"]
        calendar = form["Calendar"]

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as s:
            r = await s.get(AUTH_URL, headers=HEADERS)
            r.raise_for_status()
            sid = r.json()["auth-session"]

            async def call(lookup_id: str, no_retry: str = "true") -> dict:
                resp = await s.post(
                    API_URL,
                    headers=HEADERS,
                    params=_params(lookup_id, sid, no_retry),
                    json={"formValues": form},
                )
                resp.raise_for_status()
                return resp.json()

            # Step 1: resolve UPRN -> USRN + full address. The lookup keys off
            # the chooseAddress/uprnfromlookup/UPRNMF fields, not qsUPRN.
            usrn_row = _rows(await call(USRN_LOOKUP_ID)).get("0", {})
            usrn = usrn_row.get("USRN", "")
            if not usrn:
                return []
            address["FULLADDR2"] = {"value": usrn_row.get("FULLADDR2", "")}
            calendar["USRN"] = {"value": usrn}

            # Step 2: get live token.
            token = _rows(await call(TOKEN_LOOKUP_ID)).get("0", {}).get("liveToken", "")
            if not token:
                return []
            calendar["liveToken"] = {"value": token}
            calendar["token"] = {"value": token}

            # Step 3: get calendar date range. Calling this lookup is required
            # before the service-details lookup returns rows.
            date_row = _rows(await call(DATE_RANGE_LOOKUP_ID)).get("0", {})
            calendar["calstartDate"] = {"value": date_row.get("calstartDate", "")}
            calendar["calendDate"] = {"value": date_row.get("calendDate", "")}

            # Step 4: get per-service collection rows and parse them directly.
            # (The old schedule-HTML lookup only ever returns a "Loading..."
            # placeholder over httpx; the service-details lookup holds the
            # same data in structured form.)
            details = _service_details(
                await call(SERVICE_DETAILS_LOOKUP_ID, no_retry="false")
            )

        seen: set[tuple[date, str]] = set()
        entries: list[Collection] = []
        for text in details:
            entry = _parse_service_detail(text)
            if entry is None:
                continue
            key = (entry.date, entry["type"])
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)
        return sorted(entries, key=lambda c: c.date)
