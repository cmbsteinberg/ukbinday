"""East Cambridgeshire: AchieveForms lookup by UPRN, returning scheduled collections."""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_HOSTNAME = "eastcambs-self.achieveservice.com"
_PROCESS_ID = "2c7575a6-0139-4555-9d8a-ab504a44d989"
_STAGE_ID = "94ee5097-94db-474d-bc7a-d1796e3ab83a"
_INITIAL_URL = f"https://{_HOSTNAME}/AchieveForms/"
_AUTH_LOOKUP_ID = "69d8f92eea3cf"
_COLLECTIONS_LOOKUP_ID = "6784e74793b68"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"


class EastCambridgeshire(Scraper):
    meta = Meta(
        title="East Cambridgeshire District Council",
        url="https://www.eastcambs.gov.uk",
        lads=("E07000009",),
        cases={
            "14 Meadow Way Ely": {"uprn": "10002601730"},
            "20 Forehill Ely": {"uprn": "10002597181"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _INITIAL_URL,
            params={
                "mode": "fill",
                "consentMessage": "yes",
                "form_uri": f"sandbox-publish://AF-Process-{_PROCESS_ID}/AF-Stage-{_STAGE_ID}/definition.json",
                "process": "1",
                "process_uri": f"sandbox-processes://AF-Process-{_PROCESS_ID}",
                "process_id": f"AF-Process-{_PROCESS_ID}",
            },
            timeout=30,
        )

        sid_match = re.search(r'"auth-session":"([^"]+)"', r.text)
        if not sid_match:
            raise UpstreamError("Could not obtain session ID from East Cambs service")
        sid = sid_match.group(1)

        timestamp = int(time.time() * 1000)
        r_auth = await http.post(
            _API_URL,
            params={
                "id": _AUTH_LOOKUP_ID,
                "repeat_against": "",
                "noRetry": "false",
                "getOnlyTokens": "undefined",
                "log_id": "",
                "app_name": "AchieveForms",
                "_": timestamp,
                "sid": sid,
            },
            json={"formValues": {"Section 1": {}}},
            timeout=30,
        )
        auth_data = r_auth.json()
        auth_token = (
            auth_data.get("integration", {})
            .get("transformed", {})
            .get("rows_data", {})
            .get("0", {})
            .get("AuthenticateResponse", "")
        )

        today = date.today()
        service_start = date(2026, 6, 1)
        start_date = max(today, service_start)
        end_date = today + timedelta(days=90)

        timestamp = int(time.time() * 1000)
        r_col = await http.post(
            _API_URL,
            params={
                "id": _COLLECTIONS_LOOKUP_ID,
                "repeat_against": "",
                "noRetry": "false",
                "getOnlyTokens": "undefined",
                "log_id": "",
                "app_name": "AchieveForms",
                "_": timestamp,
                "sid": sid,
            },
            json={
                "formValues": {
                    "Section 1": {
                        "AuthenticateResponse": {"value": auth_token},
                        "selected_uprn": {"value": address.need("uprn")},
                        "MinimumDateForNextDates": {
                            "value": start_date.strftime("%Y-%m-%d")
                        },
                        "MaximumDateFormattedNext": {
                            "value": end_date.strftime("%Y-%m-%d")
                        },
                    }
                }
            },
            timeout=30,
        )
        col_data = r_col.json()

        select_data = (
            col_data.get("integration", {})
            .get("transformed", {})
            .get("select_data", [])
        )
        if not select_data:
            raise AddressNotFound(f"East Cambridgeshire has no collections for UPRN {address.need('uprn')}")

        collections = []
        for item in select_data:
            label = item.get("label", "")
            parts = label.rsplit(" - ", 1)
            if len(parts) != 2:
                continue
            bin_type, date_str = parts
            try:
                collection_date = datetime.strptime(date_str, "%d/%m/%Y").date()
            except ValueError:
                continue
            collections.append(Collection(collection_date, bin_type.strip()))

        return collections


SCRAPER = EastCambridgeshire()
