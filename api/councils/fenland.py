"""Fenland: search the postcode, select the matching house number, then load its collection schedule."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from api.councils._base import (
    Address,
    AddressNotFound,
    Blocker,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
)

_FIND_URL = "https://www.fenland.gov.uk/find"
_ICON_MAP = {
    "Empty Bin GREEN 240": "mdi:trash-can",
    "Empty Bin REFUSE SACK": "mdi:trash-can",
    "Empty Bin BLUE 240": "mdi:recycle",
    "Empty Bin RECYCLING SACK": "mdi:recycle",
    "Empty Bin BROWN 240": "mdi:leaf",
}


class Fenland(Scraper):
    meta = Meta(
        title="Fenland District Council",
        url="https://www.fenland.gov.uk/",
        lads=("E07000010",),
        cases={
            "Address1": {"postcode": "PE13 1JR", "house_number": "Flat 1"},
            "Address2": {"postcode": "PE15 0SD", "house_number": "1"},
        },
    )
    requires = frozenset({"postcode", "house_number"})
    blocker = Blocker.BOT_PROTECTION  # its site blocks Vercel's IPs (scripts/vercel_probe.py)
    headers = {"Accept": "application/json"}
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        house_number = address.need("house_number")

        r = await http.get(
            _FIND_URL,
            params={"type": "postcodesearch", "postcode": postcode},
        )
        addresses = r.json()
        if len(addresses) == 0:
            raise AddressNotFound(f"No addresses found for postcode {postcode}")

        address_ids = [
            candidate
            for candidate in addresses
            if re.search(f"^{house_number} ", candidate["line1"])
        ]

        if len(address_ids) == 0:
            raise AddressNotFound(
                f"No address found for house number {house_number}",
                [(candidate["line1"].split(" ")[0]) for candidate in addresses],
            )

        selected = address_ids[0]
        r = await http.get(
            _FIND_URL,
            params={
                "type": "loadlayer",
                "layerId": 2,
                "uprn": selected["udprn"],
                "lat": selected["latitude"],
                "lng": selected["longitude"],
            },
        )

        collections = r.json()["features"][0]["properties"]["upcoming"]
        entries = []
        for collection_date_dict in collections:
            collection_date = datetime.strptime(
                collection_date_dict["date"], "%Y-%m-%dT%H:%M:%SZ"
            )
            if collection_date.hour == 23:
                collection_date = (timedelta(days=1) + collection_date).date()
            else:
                collection_date = collection_date.date()
            for collection in collection_date_dict["collections"]:
                entries.append(
                    Collection(
                        date=collection_date,
                        type=collection["desc"],
                    )
                )

        return entries


SCRAPER = Fenland()
