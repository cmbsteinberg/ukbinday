"""Cherwell: look up bin collections by UPRN on the council's bin page."""

from __future__ import annotations

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    parse_date,
    soup,
    text_of,
)

PAGE = "https://www.cherwell.gov.uk/homepage/129/"


class Cherwell(Scraper):
    meta = Meta(
        title="Cherwell District Council",
        url="https://www.cherwell.gov.uk",
        lads=("E07000177",),
        cases={
            "Test_001": {"uprn": "100120758315"},
            "Test_002": {"uprn": "100120780449"},
            "Test_003": {"uprn": "100120777153"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        r = await http.get(PAGE, params={"uprn": uprn})
        page = soup(r.text)

        collections = []
        for box in page.find_all("div", class_="boxed"):
            title = (
                text_of(box.find("h3", class_="bin-collection-tasks__heading"))
                .replace("Your next ", "")
                .replace(" collection", "")
            )
            day = parse_date(text_of(box.find("p", class_="bin-collection-tasks__date")).strip())
            collections.append(Collection(day, title))
        return collections


SCRAPER = Cherwell()
