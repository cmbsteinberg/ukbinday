"""Burnley: AchieveForms lookup keyed on the UPRN, returning the next collection dates."""

from __future__ import annotations

from time import time_ns

from api.councils._base import Address, Collection, Http, Meta, Scraper, parse_date

_BASE = "https://your.burnley.gov.uk"
_AUTH_URL = (
    "https://your.burnley.gov.uk/authapi/isauthenticated?uri=https%253A%252F%252Fyour.burnley.gov.uk"
    "%252Fen%252FAchieveForms%252F%253Fform_uri%253Dsandbox-publish%253A%252F%252FAF-Process-b41dcd03"
    "-9a98-41be-93ba-6c172ba9f80c%252FAF-Stage-edb97458-fc4d-4316-b6e0-85598ec7fce8"
    "%252Fdefinition.json%2526redirectlink%253D%25252Fen%2526cancelRedirectLink%253D%25252Fen"
    "%2526consentMessage%253Dyes&hostname=your.burnley.gov.uk&withCredentials=true"
)


class Burnley(Scraper):
    meta = Meta(
        title="Burnley Council",
        url="https://burnley.gov.uk",
        lads=("E07000117",),
        cases={
            "Test_001": {"uprn": "100010341681"},
            "Test_002": {"uprn": "100010358864"},
            "Test_003": {"uprn": "100010357864"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)

        await http.get(f"{_BASE}/apibroker/domain/your.burnley.gov.uk?_=\
{time_ns() // 1_000_000}")

        sid_response = await http.get(_AUTH_URL)
        sid = sid_response.json()["auth-session"]

        timestamp = time_ns() // 1_000_000
        payload = {"formValues": {"Section 1": {"case_uprn1": {"value": uprn}}}}
        schedule_response = await http.post(
            f"{_BASE}/apibroker/runLookup?id=607fe757df87c&repeat_against=&noRetry=false"
            f"&getOnlyTokens=undefined&log_id=&app_name=AF-Renderer::Self&_{timestamp}&sid={sid}",
            json=payload,
        )
        rowdata = schedule_response.json()["integration"]["transformed"]["rows_data"]

        collections = []
        for item in rowdata:
            waste, day_text = rowdata[item]["display"].split(" - ")
            collections.append(Collection(parse_date(day_text), waste))
        return collections


SCRAPER = Burnley()
