"""Three Rivers: an AchieveForms token lookup followed by a UPRN-based collection schedule."""

from __future__ import annotations

from datetime import datetime, timedelta
from time import time_ns

from api.councils._base import Address, Collection, Http, Meta, Scraper

_HOST = "https://my.threerivers.gov.uk"
_AUTH_URL = (
    f"{_HOST}/authapi/isauthenticated?uri=https%253A%252F%252Fmy.threerivers.gov.uk"
    "%252Fen%252FAchieveForms%252F%253Fmode%253Dfill%2526consentMessage%253Dyes"
    "%2526form_uri%253Dsandbox-publish%253A%252F%252FAF-Process-52df96e3-992a-4b39"
    "-bba3-06cfaabcb42b%252FAF-Stage-01ee28aa-1584-442c-8d1f-119b6e27114a"
    "%252Fdefinition.json%2526process%253D1%2526process_uri%253Dsandbox-processes"
    "%253A%252F%252FAF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b"
    "%2526process_id%253DAF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b"
    "%2526noLoginPrompt%253D1&hostname=my.threerivers.gov.uk&withCredentials=true"
)
_API_URL = f"{_HOST}/apibroker/"
_TOKEN_LOOKUP_ID = "58986058d4be0"
_SCHEDULE_LOOKUP_ID = "58ac332f9e831"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{_HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}


def _api_params(lookup_id: str, sid: str, *, no_retry: str = "true") -> dict[str, str]:
    return {
        "api": "RunLookup",
        "id": lookup_id,
        "repeat_against": "",
        "noRetry": no_retry,
        "getOnlyTokens": "undefined",
        "log_id": "",
        "app_name": "AF-Renderer::Self",
        "_": str(time_ns() // 1_000_000),
        "sid": sid,
    }


class ThreeRivers(Scraper):
    meta = Meta(
        title="Three Rivers District Council",
        url="https://www.threerivers.gov.uk",
        lads=("E07000102",),
        cases={"Test_001": {"uprn": "100080913662"}},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        now = datetime.now()
        two_weeks = now + timedelta(days=14)

        r = await http.get(_AUTH_URL)
        sid = r.json()["auth-session"]

        base_form = {
            "Your address details": {
                "UPRN": {"value": uprn},
                "todaysdate": {"value": now.strftime("%Y-%m-%dT00:00:00")},
            }
        }

        r = await http.post(
            _API_URL,
            params=_api_params(_TOKEN_LOOKUP_ID, sid),
            json={"formValues": base_form},
        )
        token_data = r.json()
        token = (
            token_data.get("integration", {})
            .get("transformed", {})
            .get("rows_data", {})
            .get("0", {})
            .get("token", "")
        )

        schedule_form = {
            "Your address details": {
                "UPRN": {"value": uprn},
                "todaysdate": {"value": now.strftime("%Y-%m-%dT00:00:00")},
                "twoweeks": {"value": two_weeks.strftime("%Y-%m-%dT00:00:00")},
            },
            "Your collection dates": {
                "token": {"value": token},
            },
        }
        r = await http.post(
            _API_URL,
            params=_api_params(_SCHEDULE_LOOKUP_ID, sid, no_retry="false"),
            json={"formValues": schedule_form},
        )
        data = r.json()

        rows_data = data.get("integration", {}).get("transformed", {}).get("rows_data", {})
        if not rows_data:
            return []

        collections: list[Collection] = []
        for row in rows_data.values():
            job_name = row.get("JobName", "")
            date_str = row.get("Date", "")
            if not job_name or not date_str:
                continue
            try:
                day = datetime.strptime(date_str, "%d-%m-%Y").date()
            except ValueError:
                continue
            collections.append(Collection(date=day, type=job_name))

        return collections


SCRAPER = ThreeRivers()
