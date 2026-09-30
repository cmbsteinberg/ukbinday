"""Hinckley & Bosworth: sets a UPRN location cookie and reads collection dates from the collections page."""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    parse_date,
    soup,
)

_COLLECTIONS_URL = "https://www.hinckley-bosworth.gov.uk/collections"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


class HinckleyAndBosworth(Scraper):
    meta = Meta(
        title="Hinckley & Bosworth Borough Council",
        url="https://www.hinckley-bosworth.gov.uk",
        lads=("E07000132",),
        cases={"Test_House": {"uprn": "100030499851"}},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        location_data = {
            "postcode": "",
            "myaddress": "",
            "uprn": uprn,
            "usrn": "",
            "ward": "",
            "parish": "",
            "lng": 0,
            "lat": 0,
        }
        cookie_value = quote(json.dumps(location_data, separators=(",", ":")))
        http.cookies.set("mylocation", cookie_value, domain="www.hinckley-bosworth.gov.uk")

        response = await http.get(_COLLECTIONS_URL, timeout=10)
        page = soup(response.text)
        date_containers = page.find_all(
            "div", class_=re.compile(r"(first|last)_date_bins")
        )
        if not date_containers:
            raise AddressNotFound(
                f"No collection containers found for UPRN {uprn} — page structure may have changed."
            )

        entries: list[Collection] = []
        for container in date_containers:
            heading = container.find("h3", class_="collectiondate")
            if not heading:
                continue

            raw_date = re.sub(r"[^a-zA-Z0-9 ]", "", heading.get_text(strip=True)).strip()
            try:
                collection_date = parse_date(raw_date)
            except ValueError:
                continue

            for image in container.find_all("img"):
                title = (image.get("title") or image.get("alt") or "").lower()

                waste_type = None
                if "refuse" in title or "black" in title:
                    waste_type = "Refuse"
                elif "recycling" in title or "blue" in title or "lid" in title:
                    waste_type = "Recycling"
                elif "garden" in title or "brown" in title:
                    waste_type = "Garden"
                elif "food" in title or "caddy" in title:
                    waste_type = "Food"

                if waste_type:
                    entries.append(Collection(collection_date, waste_type))

        return entries


SCRAPER = HinckleyAndBosworth()
