"""East Riding: fetches the postcode schedule from its recycling API and filters by UPRN."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError

_SCRIPT_URL = "https://www.eastriding.gov.uk/templates/eryc_corptranet/js/eryc-bin-checker.js"
_API_URL = "https://wasterecyclingapi.eastriding.gov.uk/api/RecyclingData/CollectionsData"
_API_KEY_PATTERN = r"APIKey=(.+)&L"
_LICENSEE_PATTERN = r"Licensee=(.+)&"
_DATE_KEYS = ("BlueDate", "GreenDate", "BrownDate")


class EastRidingOfYorkshire(Scraper):
    meta = Meta(
        title="East Riding of Yorkshire Council",
        url="https://eastriding.gov.uk",
        lads=("E06000011",),
        cases={
            "Test_001": {"uprn": "010002364380", "postcode": "DN14 6BJ"},
            "Test_002": {"uprn": "100050020969", "postcode": "YO16 4HF"},
            "Test_003": {"uprn": "100050099708", "postcode": "HU12 0PE"},
        },
    )
    requires = frozenset({"uprn", "postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        script = await http.get(_SCRIPT_URL)
        try:
            api_key = re.findall(_API_KEY_PATTERN, script.text)[0]
            licensee = re.findall(_LICENSEE_PATTERN, script.text)[0]
        except IndexError as exc:
            raise UpstreamError("East Riding's bin-checker script is missing API credentials") from exc

        response = await http.get(
            _API_URL,
            params={
                "APIKey": api_key,
                "Licensee": licensee,
                "Postcode": address.need("postcode").replace(" ", ""),
            },
        )
        rows = response.json()["dataReturned"]
        uprn = address.need("uprn").zfill(12)

        collections = []
        for item in rows:
            if item["UPRN"] == uprn:
                for key in _DATE_KEYS:
                    if item[key] is not None:
                        collections.append(
                            Collection(
                                datetime.strptime(item[key], "%Y-%m-%dT00:00:00").date(),
                                key.replace("Date", " Bin"),
                            )
                        )
        return collections


SCRAPER = EastRidingOfYorkshire()
