"""Stafford: fetches the UPRN-specific address page and reads the next green and blue bin dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

API_URL = "https://www.staffordbc.gov.uk/address/"


class Stafford(Scraper):
    meta = Meta(
        title="Stafford Borough Council",
        url="https://www.staffordbc.gov.uk/",
        lads=("E07000197",),
        cases={"domestic": {"uprn": "100031780029"}},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{API_URL}{address.need('uprn')}")
        cells = soup(r.text).find_all("td")

        greenbin = cells[5]
        bluebin = cells[7]

        return [
            Collection(datetime.strptime(greenbin.get_text().strip(), "%a %d %b %Y").date(), "Green Bin"),
            Collection(datetime.strptime(bluebin.get_text().strip(), "%a %d %b %Y").date(), "Blue Bin"),
        ]


SCRAPER = Stafford()
