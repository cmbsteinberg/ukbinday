"""Mid Ulster: look up collection dates by UPRN, or find a UPRN by postcode."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
)

API_BASE = "https://midulsterbincalendar.azurewebsites.net/api"


class MidUlster(Scraper):
    meta = Meta(
        title="Mid Ulster District Council",
        url="https://www.midulstercouncil.org",
        lads=("N09000009",),
        cases={
            "Test_001": {"uprn": "185649901", "postcode": "BT71 5HY"},
        },
    )
    requires = frozenset()
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn

        if not uprn and address.postcode:
            r = await http.get(
                f"{API_BASE}/addresses/{address.postcode}",
                headers=self.headers,
                timeout=30.0,
            )
            data = r.json()
            addresses: list[dict[str, Any]] = data.get("addresses", [])
            if addresses:
                try:
                    selected = match_address(
                        address,
                        addresses,
                        text=lambda item: str(item.get("addressText", "")),
                        uprn=lambda item: item.get("uprn"),
                    )
                except AddressNotFound:
                    selected = addresses[0]
                uprn = str(selected["uprn"])

        if not uprn:
            if not address.postcode:
                raise InputError("Mid Ulster needs a UPRN or a postcode")
            return []

        r = await http.get(
            f"{API_BASE}/collectiondates/{uprn}",
            headers=self.headers,
            timeout=30.0,
        )
        data = r.json()

        collections: list[Collection] = []
        for week_key in ("lastWeek", "thisWeek", "nextWeek"):
            week = data.get(week_key)
            if not week or not week.get("date"):
                continue
            try:
                day = datetime.fromisoformat(week["date"]).date()
            except (ValueError, TypeError):
                continue
            for bin_info in week.get("bins", []):
                colour = bin_info.get("colour", "")
                name = bin_info.get("name", "")
                capacity = bin_info.get("capacity", "")
                bin_type = f"{name} ({colour})" if colour else name
                if capacity:
                    bin_type = f"{bin_type} {capacity}"
                collections.append(Collection(day, bin_type))

        return collections


SCRAPER = MidUlster()
