"""Bury Council: resolve a property by postcode or ID, then fetch its bin schedule."""

from __future__ import annotations

import re
from datetime import datetime

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

_PROPERTIES_URL = "https://www.bury.gov.uk/app-services/getProperties"
_PROPERTY_URL = "https://www.bury.gov.uk/app-services/getPropertyById"

_NAME_MAP = {
    "brown": "Garden",
    "grey": "General",
    "green": "Paper/Cardboard",
    "blue": "Plastic/Cans/Glass",
}

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Connection": "keep-alive",
    "Ocp-Apim-Trace": "true",
    "Origin": "https://bury.gov.uk",
    "Referer": "https://bury.gov.uk",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "Sec-GPC": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
}


class Bury(Scraper):
    meta = Meta(
        title="Bury Council",
        url="https://bury.gov.uk",
        lads=("E08000002",),
        cases={
            "Test_Address_001": {
                "postcode": "BL8 1DD",
                "house_number": "2",
                "street": "Oakwood Close",
            },
            "Test_Address_002": {
                "postcode": "BL8 2SG",
                "house_number": "9",
                "street": "Birkdale Drive",
            },
            "Test_Address_003": {
                "postcode": "BL8 3DG",
                "house_number": "18",
                "street": "Slaidburn Drive",
            },
        },
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        property_id = address.extra.get("id")
        if property_id is not None:
            property_id = property_id.zfill(6)
        else:
            if address.postcode is None or address.first_line is None:
                raise InputError("Specify postcode and address or just id")

            r = await http.get(
                _PROPERTIES_URL,
                params={"postcode": address.postcode},
            )
            data = r.json()
            if data["error"] is True:
                raise AddressNotFound(f"No properties found for postcode {address.postcode}")

            item = match_address(
                address,
                data["response"],
                text=lambda candidate: candidate["addressLine1"],
            )
            property_id = item["id"]

        response = await http.get(
            _PROPERTY_URL,
            params={"id": property_id},
            check=False,
        )
        data = response.json()

        collections = []
        for bin_name, bin_info in data["response"]["bins"].items():
            date_text = re.sub(r"(?<=\d)(?:st|nd|rd|th)", "", bin_info["nextCollection"])
            collections.append(
                Collection(
                    date=datetime.strptime(date_text, "%A %d %B %Y").date(),
                    type=_NAME_MAP[bin_name],
                )
            )
        return collections


SCRAPER = Bury()
