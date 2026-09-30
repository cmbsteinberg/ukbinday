"""Dudley: an AchieveForms lookup keyed on the UPRN."""

from __future__ import annotations

import time
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_SESSION_URL = (
    "https://my.dudley.gov.uk/authapi/isauthenticated?uri=https%253A%252F%252Fmy.dudley.gov.uk"
    "%252Fen%252FAchieveForms%252F%253Fform_uri%253Dsandbox-publish%253A%252F%252F"
    "AF-Process-373f5628-9aae-4e9e-ae09-ea7cd0588201%252FAF-Stage-52ec040b-10e6-440f-b964-"
    "23f924741496%252Fdefinition.json%2526redirectlink%253D%25252Fen%2526cancelRedirectLink"
    "%253D%25252Fen%2526consentMessage%253Dyes&hostname=my.dudley.gov.uk&withCredentials=true"
)
_API_URL = "https://my.dudley.gov.uk/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://my.dudley.gov.uk/fillform/?iframe_id=fillform-frame-1&db_id=",
}
_BIN_TYPES = {
    "refuseDate": "Refuse",
    "recyclingDate": "Recycling",
    "gardenDate": "Garden Waste",
}


class Dudley(Scraper):
    meta = Meta(
        title="Dudley",
        url="https://my.dudley.gov.uk",
        lads=("E08000027",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        session_response = await http.get(_SESSION_URL)
        sid = session_response.json()["auth-session"]

        response = await http.post(
            _API_URL,
            json={
                "formValues": {
                    "My bins": {
                        "uprnToCheck": {"value": uprn},
                    }
                }
            },
            headers=_HEADERS,
            params={
                "id": "64899d4c2574c",
                "repeat_against": "",
                "noRetry": "true",
                "getOnlyTokens": "undefined",
                "log_id": "",
                "app_name": "AF-Renderer::Self",
                "_": str(int(time.time() * 1000)),
                "sid": sid,
            },
        )
        rows_data = response.json()["integration"]["transformed"]["rows_data"]["0"]
        if not isinstance(rows_data, dict):
            raise UpstreamError("Invalid data returned from API")

        collections = []
        for key, value in rows_data.items():
            if key.endswith("Date") and not key.endswith("EndDate") and value:
                try:
                    day = datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    continue
                collections.append(Collection(day, _BIN_TYPES.get(key, key)))
        return collections


SCRAPER = Dudley()
