"""Rushmoor: looks up the next and previous collections by UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://www.rushmoor.gov.uk/Umbraco/Api/BinLookUpWorkAround/Get"
_HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


class Rushmoor(Scraper):
    meta = Meta(
        title="Rushmoor Borough Council",
        url="https://rushmoor.gov.uk",
        lads=("E07000092",),
        cases={"GU14": {"uprn": "100060551749"}},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _API_URL,
            params={"selectedAddress": address.need("uprn"), "weeks": "16"},
        )
        data = r.json()

        collections = []
        for collection_key in ("NextCollection", "PreviousCollection"):
            for key, value in data[collection_key].items():
                if not key.endswith("Date"):
                    continue
                waste_type = key.split("Collection")[0]
                day = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S").date()
                collections.append(Collection(day, waste_type))
        return collections


SCRAPER = Rushmoor()
