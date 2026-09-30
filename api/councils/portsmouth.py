"""Portsmouth: an AchieveForms lookup keyed on the UPRN, returning refuse and recycling dates."""

from __future__ import annotations

import time
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_SESSION_URL = (
    "https://my.portsmouth.gov.uk/en/AchieveForms/?form_uri="
    "sandbox-publish://AF-Process-26e27e70-f771-47b1-a34d-af276075cede/"
    "AF-Stage-cd7cc291-2e59-42cc-8c3f-1f93e132a2c9/definition.json"
    "&redirectlink=%2F&cancelRedirectLink=%2F"
)
_AUTH_URL = (
    "https://my.portsmouth.gov.uk/authapi/isauthenticated?uri="
    "https%3A%2F%2Fmy.portsmouth.gov.uk%2Fen%2FAchieveForms%2F%3Fform_uri%3D"
    "sandbox-publish%3A%2F%2FAF-Process-26e27e70-f771-47b1-a34d-af276075cede"
    "%2FAF-Stage-cd7cc291-2e59-42cc-8c3f-1f93e132a2c9%2Fdefinition.json"
    "%26redirectlink%3D%252F%26cancelRedirectLink%3D%252F"
    "&hostname=my.portsmouth.gov.uk&withCredentials=true"
)
_SCHEDULE_URL = (
    "https://my.portsmouth.gov.uk/apibroker/runLookup?id=5e81ed10c0241"
    "&repeat_against=&noRetry=true&getOnlyTokens=undefined&log_id="
    "&app_name=AF-Renderer::Self&_=1682697046055"
    "&sid=93c73ba547e8c23e85a50a1de67a5ca7"
)


class Portsmouth(Scraper):
    meta = Meta(
        title="Portsmouth City Council",
        url="https://www.portsmouth.gov.uk",
        lads=("E06000044",),
        cases={
            "Fawcett Road": {"uprn": "1775027540"},
            "Westbourne Road": {"uprn": "1775084532"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        await http.get(_SESSION_URL)
        auth_request = await http.get(_AUTH_URL)
        session_key = auth_request.json()["auth-session"]
        now = time.time_ns() // 1_000_000

        payload = {"formValues": {"Section 1": {"col_uprn": {"value": address.need("uprn")}}}}
        schedule_request = await http.post(
            _SCHEDULE_URL + "&_" + str(now) + "&sid=" + session_key,
            json=payload,
        )
        data = schedule_request.json()["integration"]["transformed"]["rows_data"]["0"]

        rubbish_dates = data["listRefDatesHTML"].split("<p>")[0].split("<br />")
        recycling_dates = data["listRecDatesHTML"].split("<p>")[0].split("<br />")

        collections = []
        for day in rubbish_dates:
            if len(day) > 0:
                collections.append(
                    Collection(datetime.strptime(day.rstrip("* "), "%A %d %B %Y").date(), "refuse bin")
                )

        for day in recycling_dates:
            if len(day) > 0:
                collections.append(
                    Collection(datetime.strptime(day.rstrip("* "), "%A %d %B %Y").date(), "recycling bin")
                )

        return collections


SCRAPER = Portsmouth()
