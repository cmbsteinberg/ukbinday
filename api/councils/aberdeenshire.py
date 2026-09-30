"""Aberdeenshire: fetches a property's collection table from the UPRN route endpoint."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_ROUTE_URL = "https://online.aberdeenshire.gov.uk/Apps/Waste-Collections/Routes/Route"


class Aberdeenshire(Scraper):
    meta = Meta(
        title="Aberdeenshire Council",
        url="https://aberdeenshire.gov.uk",
        lads=("S12000034",),
        cases={
            "Test_001": {"uprn": "151124612"},
            "Test_002": {"uprn": "151004105"},
            "Test_003": {"uprn": "151035884"},
        },
    )
    requires = frozenset({"uprn"})
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        response = await http.get(f"{_ROUTE_URL}/{uprn}")
        page = soup(response.text)

        collections = []
        for row in page.find_all("tr")[1:]:  # Ignore table header row
            cells = row.find_all("td")
            collections.append(
                Collection(
                    date=datetime.strptime(cells[0].text.split(" ")[0], "%d/%m/%Y").date(),
                    type=cells[1].text,
                )
            )

        return collections


SCRAPER = Aberdeenshire()
