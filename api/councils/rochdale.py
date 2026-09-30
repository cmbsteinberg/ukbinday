"""Rochdale: an AchieveForms lookup retrieves a Bartec token, then the annual bin calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
from time import time_ns

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
)

_BASE_URL = "https://rochdale-self.achieveservice.com"
_REFERER = f"{_BASE_URL}/service/Bins___view_your_waste_collection_calendar"


class Rochdale(Scraper):
    meta = Meta(
        title="Rochdale Borough Council",
        url="https://www.rochdale.gov.uk",
        lads=("E08000005",),
        cases={
            "Test_001": {"uprn": "10094359340"},
            "Test_002": {"uprn": "23030658"},
            "Test_003": {"uprn": "23011384"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": _REFERER,
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        timestamp = time_ns() // 1_000_000
        await http.get(
            f"{_BASE_URL}/apibroker/domain/rochdale-self.achieveservice.com?_={timestamp}",
            timeout=30,
        )

        auth_url = (
            f"{_BASE_URL}/authapi/isauthenticated?"
            "uri=https%3A%2F%2Frochdale-self.achieveservice.com%2Fservice%2F"
            "Bins___view_your_waste_collection_calendar"
            "&hostname=rochdale-self.achieveservice.com&withCredentials=true"
        )
        sid_response = await http.get(auth_url, timeout=30)
        sid = sid_response.json().get("auth-session")
        if not sid:
            raise UpstreamError("Rochdale API: Failed to obtain a session ID.")

        payload_token = {
            "formId": "AF-Form-d7812e2d-2876-47c2-9802-8a4a3b1a2264",
            "formValues": {"Location details": {"propertyUPRN": {"value": uprn}}},
        }
        timestamp = time_ns() // 1_000_000
        token_url = (
            f"{_BASE_URL}/apibroker/runLookup?id=6846c784a46b5&repeat_against="
            f"&noRetry=false&getOnlyTokens=undefined&log_id=&app_name=AF-Renderer::Self"
            f"&_={timestamp}&sid={sid}"
        )
        token_response = await http.post(token_url, json=payload_token, timeout=30)

        try:
            bartec_token = token_response.json()["integration"]["transformed"]["rows_data"]["0"]["bartecToken"]
        except KeyError:
            raise InputError(f"Rochdale API: Failed to retrieve bartecToken for UPRN {uprn}.") from None

        now = datetime.now()
        min_date = now.strftime("%Y-%m-%dT00:00:00")
        max_date = (now + timedelta(days=365)).strftime("%Y-%m-%dT23:59:59")
        payload_data = {
            "formId": "AF-Form-d7812e2d-2876-47c2-9802-8a4a3b1a2264",
            "formValues": {
                "Location details": {
                    "propertyUPRN": {"value": uprn},
                    "bartecToken": {"value": bartec_token},
                    "dateAnnualMinimum": {"value": min_date},
                    "dateAnnualMaximum": {"value": max_date},
                }
            },
        }
        timestamp = time_ns() // 1_000_000
        api_url = (
            f"{_BASE_URL}/apibroker/runLookup?id=68b58a1364572&repeat_against="
            f"&noRetry=true&getOnlyTokens=undefined&log_id=&app_name=AF-Renderer::Self"
            f"&_={timestamp}&sid={sid}"
        )
        data_response = await http.post(api_url, json=payload_data, timeout=30)
        data = data_response.json()

        rows_data = data.get("integration", {}).get("transformed", {}).get("rows_data", {})
        row = rows_data.get("0")
        if not row or "bartecAnnualBin1Type" not in row:
            raise InputError("Rochdale API: Failed to fetch calendar data or missing required fields.")

        collections: list[Collection] = []
        for index in range(1, 17):
            bin_type = row.get(f"bartecAnnualBin{index}Type")
            day = row.get(f"bartecAnnualBin{index}Day")
            month = row.get(f"bartecAnnualBin{index}Month")

            if bin_type and day and month:
                date_string = f"{day} {month} {now.year}"
                collection_date = datetime.strptime(date_string, "%d %B %Y").date()
                if collection_date < now.date() - timedelta(days=31):
                    collection_date = collection_date.replace(year=now.year + 1)
                collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Rochdale()
