import logging
from datetime import datetime

import httpx
from api.compat.hacs import Collection
from api.compat.hacs.exceptions import (
    SourceArgumentNotFound,
    SourceArgumentNotFoundWithSuggestions,
)

TITLE = "Cambridge City Council (Deprecated)"
DESCRIPTION = (
    "Source for cambridge.gov.uk services for Cambridge and part of Cambridgeshire"
)
URL = "https://cambridge.gov.uk"
TEST_CASES = {
    "houseNumber": {"postcode": "CB13JD", "house_number": 37},
    "houseName": {"postcode": "cb215hd", "house_number": "ROSEMARY HOUSE"},
}

API_URLS = {
    "address_search": "https://servicelayer3c.azure-api.net/wastecalendar/address/search/",
    "collection": "https://servicelayer3c.azure-api.net/wastecalendar/collection/search/{}/",
}

ICON_MAP = {
    "DOMESTIC": "mdi:trash-can",
    "RECYCLE": "mdi:recycle",
    "ORGANIC": "mdi:leaf",
}

_LOGGER = logging.getLogger(__name__)


class Source:
    def __init__(self, postcode: str, house_number: str):
        self._postcode = postcode
        self._house_number = str(house_number).capitalize()

    async def fetch(self):
        # fetch location id
        r = await httpx.AsyncClient(follow_redirects=True).get(
            API_URLS["address_search"], params={"postCode": self._postcode}
        )
        r.raise_for_status()
        addresses = r.json()
        if len(addresses) == 0:
            raise SourceArgumentNotFound("postcode", self._postcode)

        address_ids = [
            x["id"] for x in addresses if x["houseNumber"].capitalize() == self._house_number
        ]

        if len(address_ids) == 0:
            raise SourceArgumentNotFoundWithSuggestions(
                "house_number",
                self._house_number,
                [x["houseNumber"] for x in addresses],
            )

        q = str(API_URLS["collection"]).format(address_ids[0])
        r = await httpx.AsyncClient(follow_redirects=True).get(q)
        r.raise_for_status()

        collections = r.json()["collections"]
        entries = []

        for collection in collections:
            for round_type in collection["roundTypes"]:
                entries.append(
                    Collection(
                        date=datetime.strptime(
                            collection["date"], "%Y-%m-%dT%H:%M:%SZ"
                        ).date(),
                        t=round_type.title(),
                        icon=ICON_MAP.get(round_type),
                    )
                )

        return entries
