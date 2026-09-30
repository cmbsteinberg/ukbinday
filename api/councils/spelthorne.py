"""Spelthorne: AchieveForms plus a CSRF token (`api/nextref`) and a one-time lookup token.

The collections lookup returns one row with previous and next dates per service.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)
from api.councils._platforms.achieveforms import init_session, run_lookup

_HOSTNAME = "spelthorne-self.achieveservice.com"
_BASE_URL = f"https://{_HOSTNAME}"
_API_URL = f"{_BASE_URL}/apibroker/runLookup"
_TOKEN_LOOKUP_ID = "5f97e6e09fedd"
_COLLECTION_LOOKUP_ID = "66042a164c9a5"

# (previous field, next field, waste type)
_WASTE_FIELDS = [
    ("GwPrevCollection", "GwNextCollection", "Garden Waste"),
    ("RefPrevCollection", "RefNextCollection", "Refuse"),
    ("RecPrevCollection", "RecNextCollection", "Recycling"),
]


class Spelthorne(Scraper):
    meta = Meta(
        title="Spelthorne Borough Council",
        url="https://www.spelthorne.gov.uk",
        lads=("E07000213",),
        cases={"241 Thames Side Chertsey": {"uprn": "33042469"}},
    )
    requires = frozenset({"uprn"})
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        sid = await init_session(
            http,
            f"{_BASE_URL}/service/Waste_Collections",
            f"{_BASE_URL}/authapi/isauthenticated",
            _HOSTNAME,
            auth_test_url=f"{_BASE_URL}/apibroker/domain/{_HOSTNAME}",
        )
        r = await http.get(f"{_BASE_URL}/api/nextref", params={"sid": sid}, timeout=30)
        csrf = r.json()["data"]["csrfToken"]

        # A server-generated one-time token is needed before the lookup.
        r = await http.get(
            _API_URL,
            params={
                "id": _TOKEN_LOOKUP_ID,
                "repeat_against": "",
                "noRetry": "true",
                "getOnlyTokens": "undefined",
                "log_id": "",
                "app_name": "AF-Renderer::Self",
                "_": int(time.time() * 1000),
                "sid": sid,
            },
            timeout=30,
        )
        token = (
            r.json().get("integration", {}).get("transformed", {}).get("rows_data", {}).get("0", {}).get("tokenString", "")
        )
        if not token:
            raise UpstreamError("Spelthorne returned no authentication token")

        today = date.today()
        result = await run_lookup(
            http,
            _API_URL,
            sid,
            _COLLECTION_LOOKUP_ID,
            {
                "Property details": {
                    "token": {"value": token},
                    "uprn1": {"value": uprn},
                    "last2Weeks": {"value": (today - timedelta(days=14)).isoformat()},
                    "endDate": {"value": (today + timedelta(days=90)).isoformat()},
                }
            },
            no_retry="true",
            headers={"X-CSRF-Token": csrf},
        )
        row = result.get("integration", {}).get("transformed", {}).get("rows_data", {}).get("0", {})
        if row.get("NoRecordMessage", "").strip():
            raise AddressNotFound(f"Spelthorne does not know UPRN {uprn}")

        collections = []
        for prev_field, next_field, waste_type in _WASTE_FIELDS:
            for text in (row.get(prev_field, ""), row.get(next_field, "")):
                text = text.strip()
                if not text:
                    continue
                try:
                    collections.append(Collection(date.fromisoformat(text), waste_type))
                except ValueError:
                    continue
        return collections


SCRAPER = Spelthorne()
