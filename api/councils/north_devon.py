"""North Devon: AchieveForms lookups resolve a UPRN, obtain a live token, then read service dates."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from time import time_ns
from typing import Any
from xml.etree import ElementTree

from api.councils._base import Address, Collection, Http, Meta, Scraper

TITLE = "North Devon Council"
URL = "https://www.northdevon.gov.uk"

HOST = "https://my.northdevon.gov.uk"
AUTH_URL = (
    f"{HOST}/authapi/isauthenticated?uri=https%253A%252F%252Fmy.northdevon.gov.uk"
    "%252Fservice%252FWasteRecyclingCollectionCalendar"
    "&hostname=my.northdevon.gov.uk&withCredentials=true"
)
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


def _params(lookup_id: str, sid: str, no_retry: str = "true") -> dict[str, str]:
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


def _rows(resp_json: dict[str, Any]) -> dict[str, Any]:
    rows = resp_json.get("integration", {}).get("transformed", {}).get("rows_data", {})
    return rows if isinstance(rows, dict) else {}


def _service_details(resp_json: dict[str, Any]) -> list[str]:
    """Extract ServiceDetail values from the lookup's XML payload, with a regex fallback."""
    data = resp_json.get("data") or "<Responses/>"
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        root = None

    if root is not None:
        details = [
            result.text.strip()
            for result in root.iter("result")
            if result.get("column") == "ServiceDetail" and result.text
        ]
        if details:
            return details

    raw_data = resp_json.get("data") or ""
    return [
        match.strip()
        for match in re.findall(r'column="ServiceDetail"[^>]*>(.*?)</result>', raw_data)
        if match.strip()
    ]


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
        collection_date = datetime(int(year), int(month), int(day)).date()
    except ValueError:
        return None
    return Collection(date=collection_date, type=bin_type)


class NorthDevon(Scraper):
    meta = Meta(
        title=TITLE,
        url=URL,
        lads=("E07000043",),
        cases={"Test_001": {"uprn": "100040249471", "postcode": "EX31 2LE"}},
    )
    requires = frozenset({"uprn"})
    headers = HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        today = date.today()
        uprn = address.need("uprn")
        form: dict[str, Any] = {
            "Your address": {
                "qsUPRN": {"value": uprn},
                "postcode_search": {"value": address.postcode_compact or ""},
                "chooseAddress": {"value": uprn},
                "uprnfromlookup": {"value": uprn},
                "UPRNMF": {"value": uprn},
                "FULLADDR2": {"value": ""},
            },
            "Calendar": {
                "FULLADDR": {"value": ""},
                "token": {"value": ""},
                "uPRN": {"value": uprn},
                "calstartDate": {"value": ""},
                "calendDate": {"value": ""},
                "UPRN": {"value": uprn},
                "liveToken": {"value": ""},
                "USRN": {"value": ""},
                "StartDate": {"value": (today - timedelta(days=31)).isoformat()},
                "EndDate": {"value": (today + timedelta(days=1)).isoformat()},
            },
            "Print version": {"OutText2": {"value": ""}},
        }
        address_form = form["Your address"]
        calendar = form["Calendar"]

        response = await http.get(AUTH_URL, timeout=30.0)
        sid = response.json()["auth-session"]

        async def call(lookup_id: str, no_retry: str = "true") -> dict[str, Any]:
            response = await http.post(
                API_URL,
                params=_params(lookup_id, sid, no_retry),
                json={"formValues": form},
                timeout=30.0,
            )
            return response.json()

        usrn_row = _rows(await call(USRN_LOOKUP_ID)).get("0", {})
        usrn = usrn_row.get("USRN", "")
        if not usrn:
            return []
        address_form["FULLADDR2"] = {"value": usrn_row.get("FULLADDR2", "")}
        calendar["USRN"] = {"value": usrn}

        token = _rows(await call(TOKEN_LOOKUP_ID)).get("0", {}).get("liveToken", "")
        if not token:
            return []
        calendar["liveToken"] = {"value": token}
        calendar["token"] = {"value": token}

        date_row = _rows(await call(DATE_RANGE_LOOKUP_ID)).get("0", {})
        calendar["calstartDate"] = {"value": date_row.get("calstartDate", "")}
        calendar["calendDate"] = {"value": date_row.get("calendDate", "")}

        details = _service_details(
            await call(SERVICE_DETAILS_LOOKUP_ID, no_retry="false")
        )

        collections: list[Collection] = []
        for detail in details:
            collection = _parse_service_detail(detail)
            if collection is not None:
                collections.append(collection)
        return collections


SCRAPER = NorthDevon()
