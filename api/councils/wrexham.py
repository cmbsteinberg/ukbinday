"""Wrexham: an AchieveForms lookup keyed on a zero-padded UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)
from api.councils._platforms.achieveforms import first_row, init_session, run_lookup

_HOSTNAME = "myaccount.wrexham.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_DOMAIN_URL = f"https://{_HOSTNAME}/apibroker/domain/{_HOSTNAME}"
_LOOKUP_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_FORM_URI = (
    f"https://{_HOSTNAME}/en/AchieveForms/?form_uri=sandbox-publish://AF-Process-ceb55423-9f5d-4124-b713-805ac7a73e3e/"
    "AF-Stage-854336b9-1221-4e6a-88d7-785fb2f8e340/definition.json"
    "&redirectlink=/en&cancelRedirectLink=/en&consentMessage=yes&noLoginPrompt=1"
)

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
        sid = await init_session(
            http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI, auth_test_url=_DOMAIN_URL
        )

        row = first_row(
            await run_lookup(
                http,
                _LOOKUP_URL,
                sid,
                "5beab9a792bb5",
                {
                    "Section 1": {
                        "UPRN": {"value": address.need("uprn").zfill(12)},
                        "NoWeeks": {"name": "NoWeeks", "value": "2"},
                    }
                },
            )
        )
        if row is None or "UpcomingCollections" not in row:
            raise UpstreamError("Wrexham returned no upcoming collections")
        html_content = row["UpcomingCollections"]

        entries = []
        for table_row in soup(html_content).find_all("tr")[1:]:
            cells = table_row.find_all("td")
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
