"""BCP Council: discover the Logic App endpoint from the bin page, then query it by UPRN."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_API_URL = "https://bcpportal.bcpcouncil.gov.uk/checkyourbincollection/"
_API_URL_REGEX = re.compile(
    r'function fetchBinCollectionData.*?const response = await fetch\("(.*?)"',
    re.MULTILINE | re.DOTALL,
)


class Bournemouth(Scraper):
    meta = Meta(
        title="BCP Council",
        url="https://bcpportal.bcpcouncil.gov.uk",
        lads=("E06000058",),
        cases={
            "Test_001": {"uprn": "10013449141"},
            "Test_002": {"uprn": "10001085438"},
            "Test_003": {"uprn": "100040567667"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL)
        api_url = _API_URL_REGEX.search(r.text)
        if not api_url:
            raise UpstreamError("Could not find API URL in the BCP response.")

        response = await http.post(
            api_url.group(1),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "HomeAssistant-BCP/1.0",
            },
            json={"uprn": address.need("uprn")},
        )

        bin_data = response.json().get("data", [])
        collections: list[Collection] = []

        for bin_entry in bin_data:
            bin_type = bin_entry.get("wasteContainerUsageTypeDescription", "Unknown")
            for date_str in bin_entry.get("scheduleDateRange", []):
                try:
                    collection_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue
                collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Bournemouth()
