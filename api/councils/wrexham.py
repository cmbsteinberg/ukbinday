"""Wrexham: an AchieveForms lookup keyed on a zero-padded UPRN."""

from __future__ import annotations

from datetime import datetime
from time import time_ns

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_AUTH_URL = "https://myaccount.wrexham.gov.uk/authapi/isauthenticated"
_DOMAIN_URL = "https://myaccount.wrexham.gov.uk/apibroker/domain/myaccount.wrexham.gov.uk"
_LOOKUP_URL = "https://myaccount.wrexham.gov.uk/apibroker/runLookup"

_TYPE_MAP = {
    "recycling": "Recycling",
    "food": "Food Waste",
    "general": "General Waste",
    "garden": "Garden Waste",
}


class Wrexham(Scraper):
    meta = Meta(
        title="Wrexham County Borough Council",
        url="https://www.wrexham.gov.uk/",
        lads=("W06000006",),
        cases={
            "Duck Farm, Gresford, LL12 8YT": {"uprn": "100100940408"},
            "Regent St, Wrexham, LL11 1SA": {"uprn": "10096241365"},
            "Hill Crest, Wrexham, LL13 8RN": {"uprn": "100100860092"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        sid_request = await http.get(
            _AUTH_URL,
            params={
                "uri": "https://myaccount.wrexham.gov.uk/en/AchieveForms/?form_uri=sandbox-publish://AF-Process-ceb55423-9f5d-4124-b713-805ac7a73e3e/AF-Stage-854336b9-1221-4e6a-88d7-785fb2f8e340/definition.json&redirectlink=/en&cancelRedirectLink=/en&consentMessage=yes&noLoginPrompt=1",
                "hostname": "myaccount.wrexham.gov.uk",
                "withCredentials": True,
            },
        )
        sid = sid_request.json()["auth-session"]

        await http.get(
            _DOMAIN_URL,
            params={"_": time_ns() // 1_000_000, "sid": sid},
        )

        payload = {
            "formValues": {
                "Section 1": {
                    "UPRN": {"value": address.need("uprn").zfill(12)},
                    "NoWeeks": {
                        "name": "NoWeeks",
                        "value": "2",
                    },
                }
            }
        }
        params = {
            "id": "5beab9a792bb5",
            "repeat_against": "",
            "noRetry": False,
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "_": time_ns() // 1_000_000,
            "sid": sid,
        }

        schedule_request = await http.post(_LOOKUP_URL, params=params, json=payload)
        rowdata = schedule_request.json()["integration"]["transformed"]["rows_data"]
        html_content = rowdata["0"]["UpcomingCollections"]

        entries = []
        for row in soup(html_content).find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) >= 2:
                day = datetime.strptime(cells[0].text.strip(), "%d/%m/%Y").date()
                bins = cells[1].find_all("li")

                for bin_item in bins:
                    text = bin_item.get_text(strip=True).lower()

                    if "recycling" in text:
                        entries.append(Collection(day, _TYPE_MAP["recycling"]))
                    if "food" in text:
                        entries.append(Collection(day, _TYPE_MAP["food"]))
                    if "garden" in text:
                        entries.append(Collection(day, _TYPE_MAP["garden"]))
                    if "general" in text:
                        entries.append(Collection(day, _TYPE_MAP["general"]))

        return entries


SCRAPER = Wrexham()
