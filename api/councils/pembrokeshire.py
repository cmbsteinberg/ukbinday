"""Pembrokeshire: sends the UPRN to its waste API and reads the returned bin dates."""

from __future__ import annotations

import ast
from datetime import datetime

from api.councils._base import Address, AddressNotFound, Collection, Http, Meta, Scraper

_API_URL = "https://www.pembrokeshire.gov.uk/template/waste/api.asp"

_TYPE_MAP = {
    "FOODCAD": "GREEN CADDY",
    "BLUEBOX": "BLUE BOX",
    "GREENBOX": "GREEN BOX",
    "BLUEBAG": "BLUE BAG",
    "REDBAG": "RED BAG",
    "GREYBAG": "BLACK/GREY BAGS",
}


class Pembrokeshire(Scraper):
    meta = Meta(
        title="Pembrokeshire County Council",
        url="https://www.pembrokeshire.gov.uk/",
        lads=("W06000009",),
        cases={
            "Dew Street": {"uprn": "100100283349"},
            "Heol Cleddau": {"uprn": "100100281816"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        params = {
            "action": "dates",
            "public": "true",
            "uprn": uprn,
            "language": "eng",
        }
        response = await http.post(_API_URL, params=params)
        result = ast.literal_eval(response.text)

        if result["error"] == "true":
            raise AddressNotFound(f"Pembrokeshire has no bin schedule for UPRN {uprn}")

        collections = []
        for bin_entry in result["bins"]:
            day = datetime.strptime(bin_entry["nextdate"], "%d/%m/%Y").date()
            bin_type = bin_entry["type"]
            collections.append(Collection(day, _TYPE_MAP.get(bin_type, bin_type)))
        return collections


SCRAPER = Pembrokeshire()
