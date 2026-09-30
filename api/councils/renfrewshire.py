"""Renfrewshire: fetches the UPRN-specific bin calendar and parses its embedded JSON."""

from __future__ import annotations

import json
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

_API_URL = (
    "https://www.renfrewshire.gov.uk/bins-and-recycling/bin-collection/"
    "bin-collection-calendar/check-your-bin-collection-day/view/"
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)


class Renfrewshire(Scraper):
    meta = Meta(
        title="Renfrewshire Council",
        url="https://renfrewshire.gov.uk/",
        lads=("S12000038",),
        cases={
            "Test_001": {"postcode": "PA12 4JU", "uprn": "123033059"},
            "Test_002": {"postcode": "PA12 4AJ", "uprn": "123034174"},
            "Test_003": {"postcode": "PA2 9JB", "uprn": "123046497"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{_API_URL}{address.need('uprn')}")
        page = soup(r.text)
        collections_data = page.find(
            "script", {"type": "application/json", "id": "collections-data"}
        )
        if collections_data is None:
            raise UpstreamError("Renfrewshire did not provide bin collection data")

        try:
            bin_data = json.loads(collections_data.get_text(strip=True))
        except json.JSONDecodeError as exc:
            raise UpstreamError(f"Renfrewshire returned invalid collection JSON: {exc}") from exc

        collections = []
        for date_str, bins in bin_data.items():
            day = datetime.fromisoformat(date_str).date()
            for details in bins.values():
                if details is None:
                    continue
                collections.append(Collection(day, details["ShortName"]))
        return collections


SCRAPER = Renfrewshire()
