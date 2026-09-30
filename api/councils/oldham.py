"""Oldham: looks up bin collection dates by UPRN on the council portal."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup, text_of

PAGE = "https://portal.oldham.gov.uk/bincollectiondates/details"


class Oldham(Scraper):
    meta = Meta(
        title="Oldham Council",
        url="https://oldham.gov.uk/",
        lads=("E08000004",),
        cases={
            "Test_001": {"uprn": "422000125973"},
            "Test_002": {"uprn": "422000129104"},
            "Test_003": {"uprn": "422000042299"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(PAGE, params={"uprn": address.need("uprn")})
        page = soup(r.content)

        collections = []
        for item in page.find_all("table", {"class": "data-table confirmation"}):
            bin_type = text_of(item.find("th"))
            day = text_of(item.find("td", {"class": "coltwo"}))
            collections.append(
                Collection(datetime.strptime(day, "%d/%m/%Y").date(), bin_type)
            )
        return collections


SCRAPER = Oldham()
