"""Hull: looks up the UPRN at the bin-collection endpoint and parses its JSON dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://www.hull.gov.uk/ajax/bin-collection"
_REFERER = "https://www.hull.gov.uk"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"
)


class KingstonUponHull(Scraper):
    meta = Meta(
        title="Hull City Council",
        url="https://hull.gov.uk/",
        lads=("E06000010",),
        cases={
            "21095794": {"uprn": "21095794"},
            "21009164": {"uprn": "21009164"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"Referer": _REFERER, "User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL, params={"bindate": address.need("uprn")})

        data = r.json()
        data = data[0] if isinstance(data[0], list) else data

        collections = []
        for entry in data:
            day = datetime.strptime(entry["next_collection_date"], "%Y-%m-%d").date()
            bin_type = entry["collection_type"]
            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = KingstonUponHull()
