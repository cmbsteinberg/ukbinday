"""Wyre: looks up a property's bin collections by its 12-digit UPRN."""

from __future__ import annotations

from dateutil import parser

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_API_URL = "https://www.wyre.gov.uk/bincollections"


class Wyre(Scraper):
    meta = Meta(
        title="Wyre Borough Council",
        url="https://www.wyre.gov.uk",
        lads=("E07000128",),
        cases={
            "Test_001": {"uprn": "10094000847"},
            "Test_002": {"uprn": "100010727065"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _API_URL,
            params={"uprn": address.need("uprn").zfill(12)},
            check=False,
        )
        page = soup(r.text)

        collections = []
        bins = page.find_all("h3", class_="bin-collection-tasks__heading")
        dates = page.find_all("p", class_="bin-collection-tasks__date")
        for date_tag, bin_tag in zip(dates, bins, strict=False):
            bin_type = " ".join(bin_tag.text.split()[2:4])
            day = parser.parse(date_tag.text).date()
            collections.append(Collection(date=day, type=bin_type))

        return collections


SCRAPER = Wyre()
