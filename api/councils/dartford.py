"""Dartford: looks up collection dates directly by UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

URL = "https://windmz.dartford.gov.uk/ufs/WS_CHECK_COLLECTIONS.eb"


class Dartford(Scraper):
    meta = Meta(
        title="Dartford Borough Council",
        url="https://dartford.gov.uk",
        lads=("E07000107",),
        cases={
            "Test_001": {"uprn": "100060862889"},
            "Test_002": {"uprn": "100060857499"},
            "Test_003": {"uprn": "200000540020"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            f"{URL}?UPRN={address.need('uprn')}",
        )

        page = soup(r.content)
        waste_types = page.find_all("td", {"data-eb-colheader": "Collection Type"})
        waste_dates = page.find_all("td", {"data-eb-colheader": "Date"})

        collections = []
        for i in range(len(waste_types)):
            waste_type = waste_types[i].text.strip()
            waste_date = waste_dates[i].text.strip()
            collections.append(
                Collection(
                    date=datetime.strptime(waste_date, "%d/%m/%Y").date(),
                    type=waste_type,
                )
            )

        return collections


SCRAPER = Dartford()
