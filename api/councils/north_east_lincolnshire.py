"""North East Lincolnshire: request the refuse schedule by UPRN and parse its HTML."""

from __future__ import annotations

from bs4 import Tag
from dateutil import parser

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    soup,
)

_API_URL = "https://www.nelincs.gov.uk/refuse-collection-schedule/"


class NorthEastLincolnshire(Scraper):
    meta = Meta(
        title="North East Lincolnshire Council",
        url="https://www.nelincs.gov.uk/",
        lads=("E06000012",),
        cases={
            "11042949": {"uprn": "11042949"},
            "11043243": {"uprn": "11043243"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL, params={"uprn": address.need("uprn")})
        page = soup(r.text)

        heading_i = page.select_one("i.fa-trash")
        if not heading_i:
            raise InputError("No collection data found for the provided UPRN.")
        collection_div = heading_i.find_parent("div")
        if not isinstance(collection_div, Tag):
            raise InputError("No collection data found for the provided UPRN.")

        collections = []
        for heading, col_list in zip(
            collection_div.select("div.h4"), collection_div.select("ul"), strict=False
        ):
            bin_type = heading.text.strip()
            for li in col_list.select("li"):
                day = parser.parse(li.text.strip(), dayfirst=True).date()
                collections.append(Collection(day, bin_type))

        return collections


SCRAPER = NorthEastLincolnshire()
