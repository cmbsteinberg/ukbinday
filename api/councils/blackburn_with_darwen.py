"""Blackburn with Darwen: fetches twelve months of bin collections by UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = "https://mybins.blackburn.gov.uk/api/mybins/getbincollectiondays"


class BlackburnWithDarwen(Scraper):
    meta = Meta(
        title="Blackburn with Darwen Borough Council",
        url="https://blackburn.gov.uk/",
        lads=("E06000008",),
        cases={
            "Test_001": {"uprn": "10091617919"},
            "Test_002": {"uprn": "100010732130"},
            "Test_003": {"uprn": "100010729702"},
        },
    )
    requires = frozenset({"uprn"})
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        now = datetime.now()
        year = now.year
        month = now.month
        collections = []

        for _ in range(1, 13):
            r = await http.get(
                _API_URL,
                params={"month": month, "year": year, "uprn": address.need("uprn")},
            )

            for collection_day in r.json()["BinCollectionDays"]:
                if collection_day is not None and isinstance(collection_day, list):
                    for collection in collection_day:
                        collections.append(
                            Collection(
                                date=datetime.fromisoformat(collection["CollectionDate"]).date(),
                                type=collection["BinType"],
                            )
                        )

            month += 1
            if month > 12:
                month = 1
                year += 1

        return collections


SCRAPER = BlackburnWithDarwen()
