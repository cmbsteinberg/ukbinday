"""Barking and Dagenham: looks up a UPRN and reads upcoming collections from its bin API."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://www.lbbd.gov.uk/rest/bin/{uprn}"
_HEADERS = {"user-agent": "Home-Assitant-waste-col-sched/2.11"}
_COLLECTION_MAP = {
    "Grey-Household": "General waste",
    "Brown-Recycling": "Recycling",
    "Green-Garden": "Garden waste",
}


class BarkingAndDagenham(Scraper):
    meta = Meta(
        title="London Borough of Barking and Dagenham",
        url="https://www.lbbd.gov.uk/",
        lads=("E09000002",),
        cases={
            "100 Heathway": {"uprn": "100014033"},
            "40 Porters Avenue": {"uprn": "100024629"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(
            _API_URL.format(uprn=address.need("uprn")),
            timeout=30,
            check=False,
        )
        rubbish_data = response.json()

        collections = []
        for result in rubbish_data["results"]:
            collection_type = _COLLECTION_MAP.get(result["bin_type"], result["bin_type"])
            dates = ([result["nextcollection"]] if result["nextcollection"] else []) + result["futurecollections"]
            for collection_date in dates:
                collections.append(
                    Collection(
                        datetime.strptime(collection_date, "%A %d %B %Y").date(),
                        collection_type,
                    )
                )

        return collections


SCRAPER = BarkingAndDagenham()
