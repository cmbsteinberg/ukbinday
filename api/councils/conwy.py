"""Conwy: looks up collections by UPRN from its Contensis-Forms results page."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    soup,
    text_of,
)

_API_URL = "https://www.conwy.gov.uk/Contensis-Forms/erf/collection-result-soap-xmas2025.asp"


class Conwy(Scraper):
    meta = Meta(
        title="Conwy County Borough Council",
        url="https://www.conwy.gov.uk/",
        lads=("W06000003",),
        cases={
            "50000009637": {"uprn": "50000009637"},
            "100101037037": {"uprn": "100101037037"},
            "50000007574": {"uprn": "50000007574"},
        },
    )
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _API_URL,
            params={"uprn": address.need("uprn"), "ilangid": 1},
        )

        collection_dates = soup(r.text).select(".containererf")
        if not collection_dates:
            raise AddressNotFound(f"No collections found for UPRN {address.uprn}")

        collections = []
        for collection in collection_dates:
            date_text = text_of(collection.select_one("#main #content"))
            day = datetime.strptime(date_text, "%A, %d/%m/%Y").date()

            for element in collection.select("#main1 li"):
                collections.append(Collection(day, text_of(element)))

        return collections


SCRAPER = Conwy()
