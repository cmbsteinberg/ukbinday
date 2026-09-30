"""South Holland: looks up collection dates from the council's JSON-RPC API using a UPRN."""

from __future__ import annotations

import re
from datetime import date, datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
)

_API_URL = "https://www.sholland.gov.uk/apiserver/ajaxlibrary"
_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": "https://www.sholland.gov.uk/mycollections",
}
_TYPE_LABELS = {
    "refuse": "Refuse",
    "recycling": "Recycling",
    "garden": "Garden",
}


def _parse_display_date(date_str: str) -> date | None:
    if not date_str:
        return None

    clean = re.sub(r"(\d)(st|nd|rd|th)", r"\1", date_str)
    clean = clean.replace("*", "").split("(")[0].strip()

    try:
        day = datetime.strptime(clean, "%A %d %B %Y").date()
    except ValueError:
        if re.search(r"\b\d{4}\b", clean):
            return None
        try:
            return parse_date(clean)
        except ValueError:
            return None

    today = date.today()
    if day < today:
        day = day.replace(year=day.year + 1)
    return day


class SouthHolland(Scraper):
    meta = Meta(
        title="South Holland District Council",
        url="https://www.sholland.gov.uk/",
        lads=("E07000140",),
        cases={
            "10002546801": {"uprn": "10002546801", "postcode": "PE11 2FR"},
            "PE12 7AR": {"uprn": "100030897036", "postcode": "PE12 7AR"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "SouthHolland.Waste.getCollectionDaysAjax",
            "params": {"UPRN": address.need("uprn")},
        }
        response = await http.post(_API_URL, json=payload)
        result = response.json().get("result", {})
        if not result.get("success"):
            raise UpstreamError(f"API call unsuccessful: {result!r}")

        date_map = {
            "refuse": result.get("nextRefuseDateDisplay"),
            "recycling": result.get("nextRecyclingDateDisplay"),
            "garden": result.get("nextGardenDateDisplay"),
        }
        collections = []
        for bin_type, display in date_map.items():
            collection_date = _parse_display_date(display or "")
            if collection_date is not None:
                collections.append(Collection(collection_date, _TYPE_LABELS[bin_type]))
        return collections


SCRAPER = SouthHolland()
