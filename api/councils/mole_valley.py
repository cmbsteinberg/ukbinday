"""Mole Valley: search paginated postcode results, select the property, and parse its bin schedule."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    match_address,
    soup,
)

_API_URL = "https://myproperty.molevalley.gov.uk/molevalley/api/live_addresses/"
_DATE_FORMAT = "(%a) %d/%m/%Y"
_BIN_TYPES = (
    "Refuse (black bin)",
    "Recycling (green bin)",
    "Garden Waste (brown lid)",
    "Food Waste",
)


def _feature_text(feature: dict[str, Any]) -> str:
    return str(feature["properties"]["address_string"])


def _feature_uprn(feature: dict[str, Any]) -> object:
    properties = feature["properties"]
    return properties.get("uprn", properties.get("UPRN"))


def _parse_collections(html: str) -> list[Collection]:
    page = soup(html)
    entries: list[Collection] = []

    for bin_type in _BIN_TYPES:
        label_tag = page.find("strong", string=re.compile(re.escape(bin_type)))
        if not label_tag:
            continue

        next_p = label_tag.find_next("p")
        if not next_p:
            continue

        date_tag = next_p.find("strong")
        if not date_tag:
            continue

        date_str = date_tag.get_text(strip=True)
        if "No collection" in date_str or "Not a" in date_str:
            continue

        try:
            collection_date = datetime.strptime(date_str, _DATE_FORMAT).date()
        except ValueError:
            continue

        entries.append(Collection(collection_date, bin_type))

    return entries


class MoleValley(Scraper):
    meta = Meta(
        title="Mole Valley District Council",
        url="https://www.molevalley.gov.uk",
        lads=("E07000210",),
        cases={
            "44 Chapel Court Dorking": {"postcode": "RH4 1BT", "house_number": "44"},
            "79 Ashcombe Road Dorking": {"postcode": "RH4 1LX", "house_number": "79"},
            "21 Rookery Close Fetcham": {"postcode": "KT22 9BG", "house_number": "21"},
        },
    )
    requires = frozenset({"postcode", "house_number"})
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").strip()
        address.need("house_number")
        page_number = 1
        features: list[dict[str, Any]] = []

        while True:
            response = await http.get(
                _API_URL + postcode,
                params={"page": page_number},
                timeout=30,
            )
            data = response.json()

            if not data.get("result", True):
                break

            page_features = data.get("results", {}).get("features", [])
            if not page_features:
                break

            features.extend(page_features)
            page_number += 1

        if not features:
            raise AddressNotFound(f"No properties found for {postcode}")

        feature = match_address(
            address,
            features,
            text=_feature_text,
            uprn=_feature_uprn,
        )
        return _parse_collections(feature["properties"]["three_column_layout_html"])


SCRAPER = MoleValley()
