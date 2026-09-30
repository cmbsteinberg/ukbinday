"""Waltham Forest: an AchieveForms lookup keyed on the UPRN, returning service names and next collection dates."""

from __future__ import annotations

from time import time_ns

from api.councils._base import Address, Collection, Http, Meta, Scraper, parse_date

_AUTH_URL = (
    "https://portal.walthamforest.gov.uk/authapi/isauthenticated?"
    "uri=https%253A%252F%252Fportal.walthamforest.gov.uk%252FAchieveForms%252F"
    "%253Fmode%253Dfill%2526consentMessage%253Dyes%2526form_uri%253Dsandbox-publish%253A"
    "%252F%252FAF-Process-d62ccdd2-3de9-48eb-a229-8e20cbdd6393%252FAF-Stage-"
    "8bf39bf9-5391-4c24-857f-0dc2025c67f4%252Fdefinition.json%2526process%253D1"
    "%2526process_uri%253Dsandbox-processes%253A%252F%252FAF-Process-"
    "d62ccdd2-3de9-48eb-a229-8e20cbdd6393%2526process_id%253DAF-Process-"
    "d62ccdd2-3de9-48eb-a229-8e20cbdd6393&hostname=portal.walthamforest.gov.uk"
    "&withCredentials=true"
)
_LOOKUP_URL = "https://portal.walthamforest.gov.uk/apibroker/runLookup"
_HEADERS = {"user-agent": "Mozilla/5.0"}


class WalthamForest(Scraper):
    meta = Meta(
        title="Waltham Forest",
        url="https://walthamforest.gov.uk/",
        lads=("E09000031",),
        cases={
            "200001421821": {"uprn": "200001421821"},
            "100023583909": {"uprn": "100022551607"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        sid_response = await http.get(_AUTH_URL)
        sid = sid_response.json()["auth-session"]

        timestamp = time_ns() // 1_000_000
        uprn = address.need("uprn")
        payload = {
            "formValues": {
                "Property": {
                    key: {"value": uprn}
                    for key in (
                        "AccountSiteUprn",
                        "UPRNSearch",
                        "calcUPRN",
                        "customerUPRN",
                        "inputUPRN",
                    )
                }
            }
        }

        schedule_response = await http.post(
            f"{_LOOKUP_URL}?id=5e208cda0d0a0&repeat_against=&noRetry=False"
            f"&getOnlyTokens=undefined&log_id=&app_name=AF-Renderer::Self"
            f"&_={timestamp}sid={sid}",
            json=payload,
        )
        rowdata = schedule_response.json()["integration"]["transformed"]["rows_data"]

        collections = []
        for item in rowdata.values():
            bin_type = item["ServiceName"]
            next_date = item["NextCollectionDate"]
            if next_date == " NaN ":
                continue
            try:
                day = parse_date(next_date)
            except ValueError:
                continue
            collections.append(Collection(day, bin_type))
        return collections


SCRAPER = WalthamForest()
