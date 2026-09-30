"""Cumberland: fetches the bin schedule from its UPRN-specific collection page."""

from __future__ import annotations

from datetime import datetime

from bs4 import Tag

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

PAGE = (
    "https://www.cumberland.gov.uk/bins-recycling-and-street-cleaning/"
    "waste-collections/bin-collection-schedule/view"
)


class Cumberland(Scraper):
    meta = Meta(
        title="Cumberland Council",
        url="https://cumberland.gov.uk",
        lads=("E06000063",),
        cases={
            "Test_001": {"postcode": "CA28 7QS", "uprn": "100110319463"},
            "Test_002": {"postcode": "CA28 8LG", "uprn": "100110320734"},
            "Test_003": {"postcode": "CA28 6SW", "uprn": "10000895390"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{PAGE}/{address.need('uprn')}")
        page = soup(r.content)

        collections = []
        for item in page.select("li.waste-collection__day"):
            time_node = item.select_one("time")
            type_node = item.select_one(".waste-collection__day--colour")
            if not isinstance(time_node, Tag) or not isinstance(type_node, Tag):
                continue

            waste_date = time_node["datetime"]
            waste_type = type_node.get_text(strip=True)
            collections.append(
                Collection(datetime.strptime(waste_date, "%Y-%m-%d").date(), waste_type)
            )
        return collections


SCRAPER = Cumberland()
