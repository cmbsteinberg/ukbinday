"""Gwynedd: a per-UPRN lookup returning the next collection dates as HTML."""

from __future__ import annotations

from datetime import datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    soup,
)

API_URL = "https://diogel.gwynedd.llyw.cymru/Daearyddol/en/LleDwinByw/Index/{uprn}"


class Gwynedd(Scraper):
    meta = Meta(
        title="Gwynedd",
        url="https://www.gwynedd.gov.uk/",
        lads=("W06000002",),
        cases={
            "200003177805": {"uprn": "200003177805"},
            "200003175227": {"uprn": "200003175227"},
            "10070340900": {"uprn": "10070340900"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(API_URL.format(uprn=address.need("uprn")))
        page = soup(r.text)
        collections_headline = page.find("h6", string="Next collection dates:")
        if not isinstance(collections_headline, Tag):
            raise AddressNotFound(f"No collection dates found for UPRN {address.uprn}")

        collections = collections_headline.find_next("ul").find_all("li")
        entries = []

        for collection in collections:
            if not isinstance(collection, Tag):
                continue
            for paragraph in collection.find_all("p"):
                paragraph.extract()

            bin_type, date_str = collection.text.strip().split(":")[:2]
            bin_type, date_str = bin_type.strip(), date_str.strip()
            day = datetime.strptime(date_str, "%A %d/%m/%Y").date()
            entries.append(Collection(date=day, type=bin_type))

        return entries


SCRAPER = Gwynedd()
