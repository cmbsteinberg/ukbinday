"""Orkney Islands: looks up dated bin collections by UPRN using the council's widget API."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, AddressNotFound, Collection, Http, Meta, Scraper

_API_URL = "https://www.orkney.gov.uk/actions/_orkney/bin-collection/lookup-address"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


class OrkneyIslands(Scraper):
    meta = Meta(
        title="Orkney Islands",
        url="https://www.orkney.gov.uk/bin-collections",
        lads=("S12000023",),
        cases={
            "Palace Gardens, Birsay": {"uprn": "134017306"},
            "Gill Pier, Westray": {"uprn": "134004695"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _API_URL,
            params={"addressId": address.need("uprn")},
            timeout=30,
        )
        data = r.json()

        if not data.get("success"):
            raise AddressNotFound(data.get("error") or "Address not found")

        area = data.get("binCollectionArea") or {}
        config = data.get("binConfig") or {}

        collections: list[Collection] = []
        for key, items in area.items():
            if not isinstance(items, list):
                continue
            label = (config.get(key) or {}).get("label") or key.replace("_", " ").title()
            for item in items:
                try:
                    day = datetime.strptime(item["date"], "%Y-%m-%d").date()
                except (KeyError, ValueError, TypeError):
                    continue
                collections.append(Collection(day, label))

        return collections


SCRAPER = OrkneyIslands()
