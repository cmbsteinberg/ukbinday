"""Lichfield: fetch the bin calendar page using the property's 12-digit UPRN."""

from __future__ import annotations

import re

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    parse_date,
    soup,
)

_PAGE = "https://www.lichfielddc.gov.uk/bincalendar"


class Lichfield(Scraper):
    meta = Meta(
        title="Lichfield District Council",
        url="https://lichfielddc.gov.uk",
        lads=("E07000194",),
        cases={
            "Test_001": {"uprn": "100031695248"},
            "Test_002": {"uprn": "100031704571"},
            "Test_003": {"uprn": "10002768095"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"User-Agent": "Mozilla"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(_PAGE, params={"uprn": address.need("uprn").zfill(12)})
        page = soup(response.text)
        collections = []

        for box in page.find_all("div", class_="boxed"):
            date_elements = box.find_all(
                "p", class_=re.compile("bin-collection-tasks__(date|frequency)")
            )
            if not date_elements:
                continue

            date_text = date_elements[0].contents[-1].string
            collection_date = parse_date(date_text)
            name_elements = box.find_all("h3", class_="bin-collection-tasks__heading")
            bin_type = name_elements[0].contents[1]
            collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Lichfield()
