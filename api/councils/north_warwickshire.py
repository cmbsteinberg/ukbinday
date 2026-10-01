"""North Warwickshire: AchieveForms lookups keyed on the UPRN."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_SESSION_URL = "https://nwarks-ss.achieveservice.com/authapi/isauthenticated"
_API_URL = "https://nwarks-ss.achieveservice.com/apibroker/runLookup"
_TOKEN_LOOKUP_ID = "695fc5d469d65"
_LOOKUP_IDS = ("6964f19aac313", "6964f19d080c5", "6964f19bc2e2e", "695fc85344bb3")
_REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://nwarks-ss.achieveservice.com/fillform/?iframe_id=fillform-frame-1&db_id=",
}


def _params(lookup_id: str, sid: str, no_retry: str) -> dict[str, str]:
    return {
        "id": lookup_id,
        "repeat_against": "",
        "noRetry": no_retry,
        "getOnlyTokens": "undefined",
        "log_id": "",
        "app_name": "AF-Renderer::Self",
        "_": str(int(time.time() * 1000)),
        "sid": sid,
    }


class NorthWarwickshire(Scraper):
    meta = Meta(
        title="North Warwickshire",
        url="https://www.northwarks.gov.uk",
        lads=("E07000218",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        session_response = await http.get(_SESSION_URL)
        sid = session_response.json()["auth-session"]

        token_response = await http.post(
            _API_URL,
            params=_params(_TOKEN_LOOKUP_ID, sid, "true"),
            json={
                "formValues": {
                    "Collection Details": {
                        "testOrLive": {"value": "Live"},
                    },
                },
            },
            headers=_REQUEST_HEADERS,
        )
        rows_data = token_response.json()["integration"]["transformed"]["rows_data"]["0"]
        if not isinstance(rows_data, dict):
            raise UpstreamError("Invalid data returned from North Warwickshire")
        token = rows_data["AuthenticateResponse"]

        now = datetime.now()
        data = {
            "formValues": {
                "Collection Details": {
                    "AuthenticateResponse": {"value": token},
                    "uprn": {"value": uprn},
                    "dateTodayFormatted": {"value": now.strftime("%Y-%m-%d")},
                    "date4WeeksFormatted": {
                        "value": (now + timedelta(weeks=12)).strftime("%Y-%m-%d")
                    },
                },
            },
        }

        rows: list[Any] = []
        for lookup_id in _LOOKUP_IDS:
            response = await http.post(
                _API_URL,
                params=_params(lookup_id, sid, "false"),
                json=data,
                headers=_REQUEST_HEADERS,
            )
            rows.append(response.json()["integration"]["transformed"]["rows_data"])

        collections: list[Collection] = []
        for group in rows:
            if not group:
                continue
            for item in group.values():
                bin_type = item["JobName"].strip()
                date_text = item["Date"]
                try:
                    if "-" in date_text:
                        day = datetime.strptime(date_text, "%Y-%m-%d").date()
                    elif "/" in date_text:
                        day = datetime.strptime(date_text, "%d/%m/%Y").date()
                    else:
                        continue
                except ValueError:
                    continue
                collections.append(Collection(day, bin_type))

        return collections


SCRAPER = NorthWarwickshire()
