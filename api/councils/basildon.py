"""Basildon: resolve a property by UPRN or postcode, then fetch its refuse schedule."""

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

_PROPERTIES_URL = "https://basildonportal.azurewebsites.net/api/listPropertiesByPostcode"
_SCHEDULE_URL = "https://basildonportal.azurewebsites.net/api/getPropertyRefuseInformation"

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Connection": "keep-alive",
    "Ocp-Apim-Trace": "true",
    "Origin": "https://mybasildon.powerappsportals.com",
    "Referer": "https://mybasildon.powerappsportals.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "Sec-GPC": "1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36"
    ),
}

_SERVICE_NAMES = {
    "green_waste": "Garden",
    "general_waste": "General",
    "food_waste": "Food",
    "glass_waste": "Glass",
    "papercard_waste": "Paper/Cardboard",
    "plasticcans_waste": "Plastic/Cans",
}

_COLLECTION_DATE_KEYS = (
    "current_collection_",
    "next_collection_",
    "last_collection_",
)


class Basildon(Scraper):
    meta = Meta(
        title="Basildon Council",
        url="https://basildon.gov.uk",
        lads=("E07000066",),
        cases={
            "Test_Address_001": {
                "postcode": "CM11 1BJ",
                "house_number": "6",
                "street": "HEADLEY ROAD",
            },
            "Test_Address_002": {
                "postcode": "SS14 1QU",
                "house_number": "25",
                "street": "LONG RIDING",
            },
            "Test_UPRN_001": {"uprn": "100090277795"},
        },
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn.zfill(12) if address.uprn is not None else None

        if uprn is None:
            if address.postcode is None or address.first_line is None:
                raise InputError("Basildon needs a UPRN or a postcode and address")

            response = await http.post(
                _PROPERTIES_URL,
                json={"postcode": address.postcode},
            )
            data: dict[str, Any] = response.json()
            properties = data["properties"]
            if data["result"] != "success" or not properties:
                raise AddressNotFound(f"No properties found for postcode {address.postcode}")

            selected = match_address(
                address,
                properties,
                text=lambda item: item["line1"],
                uprn=lambda item: item["uprn"],
            )
            uprn = str(selected["uprn"])

        response = await http.post(
            _SCHEDULE_URL,
            json={"uprn": uprn},
            check=False,
        )
        data = response.json()["refuse"]["available_services"]

        collections = []
        for service, name in _SERVICE_NAMES.items():
            for date_key in _COLLECTION_DATE_KEYS:
                if data[service][date_key + "active"]:
                    day = datetime.strptime(
                        data[service][date_key + "date"],
                        "%Y-%m-%d",
                    ).date()
                    collections.append(Collection(day, name))

        return collections


SCRAPER = Basildon()
