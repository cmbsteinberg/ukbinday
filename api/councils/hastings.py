"""Hastings: looks up collection dates by UPRN through its collection-days API."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://el2.hastings.gov.uk/MyArea/CollectionDays.asmx/LookupCollectionDaysByService"


class Hastings(Scraper):
    meta = Meta(
        title="Hastings Borough Council",
        url="https://www.hastings.gov.uk/",
        lads=("E07000062",),
        cases={
            "Test_001": {"uprn": "100060038877"},
            "Test_002": {"uprn": "10070609836"},
            "Test_003": {"uprn": "100060041770"},
        },
    )
    requires = frozenset({"uprn"})
    transport = __import__("api.councils._base", fromlist=["Transport"]).Transport.CURL_CFFI
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(_API_URL, json={"Uprn": address.need("uprn")})
        data = r.json()["d"]

        collections = []
        for service in data:
            waste_type: str = service["Service"].removesuffix("collection service").strip()
            for date_str in service["Dates"]:
                collections.append(
                    Collection(
                        datetime.fromtimestamp(
                            int(date_str.strip("/").removeprefix("Date").strip("()")) / 1000
                        ).date(),
                        waste_type,
                    )
                )

        return collections


SCRAPER = Hastings()
