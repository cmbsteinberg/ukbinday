"""Hounslow: authenticate with AchieveForms, fetch a Bartec token, then request the UPRN's collections."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError

_SESSION_URL = (
    "https://my.hounslow.gov.uk/authapi/isauthenticated"
    "?uri=https%253A%252F%252Fmy.hounslow.gov.uk%252Fservice%252FWaste_and_recycling_collections"
    "&hostname=my.hounslow.gov.uk&withCredentials=true"
)
_API_URL = "https://my.hounslow.gov.uk/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://my.hounslow.gov.uk/fillform/?iframe_id=fillform-frame-1&db_id=",
}


class Hounslow(Scraper):
    meta = Meta(
        title="Hounslow",
        url="https://my.hounslow.gov.uk/service/Waste_and_recycling_collections",
        lads=("E09000018",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        r = await http.get(_SESSION_URL)
        sid = r.json()["auth-session"]

        params = {
            "id": "655f4290810cf",
            "repeat_against": "",
            "noRetry": "true",
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "_": str(int(time.time() * 1000)),
            "sid": sid,
        }
        r = await http.post(_API_URL, headers=_HEADERS, params=params)

        rows_data = r.json()["integration"]["transformed"]["rows_data"]["0"]
        if not isinstance(rows_data, dict):
            raise UpstreamError("Invalid data returned from Hounslow API")
        token = rows_data["bartecToken"]

        payload = {
            "formValues": {
                "Your address": {
                    "searchUPRN": {"value": uprn},
                    "bartecToken": {"value": token},
                    "searchFromDate": {"value": datetime.now().strftime("%Y-%m-%d")},
                    "searchToDate": {
                        "value": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
                    },
                },
            },
        }
        params = {
            "id": "659eb39b66d5a",
            "repeat_against": "",
            "noRetry": "false",
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "_": str(int(time.time() * 1000)),
            "sid": sid,
        }
        r = await http.post(_API_URL, json=payload, headers=_HEADERS, params=params)

        rows_data = r.json()["integration"]["transformed"]["rows_data"]["0"]
        if not isinstance(rows_data, dict):
            raise UpstreamError("Invalid data returned from Hounslow API")

        collections = json.loads(rows_data["jobsJSON"])
        result: list[Collection] = []
        for collection in collections:
            bin_type = collection["jobType"]
            if not bin_type:
                continue
            try:
                day = datetime.strptime(collection["jobDate"], "%Y-%m-%d").date()
            except ValueError:
                continue
            result.append(Collection(day, bin_type))
        return result


SCRAPER = Hounslow()
