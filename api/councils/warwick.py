"""Warwick District Council: fetches the UPRN-specific recycling page and reads its collection dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

BASE = "https://estates7.warwickdc.gov.uk/PropertyPortal/Property/Recycling"


def _parse_date(date_string: str) -> datetime:
    try:
        return datetime.strptime(date_string, "%a %d/%m/%Y")
    except ValueError:
        return datetime.strptime(date_string, "%d/%m/%Y")


class Warwick(Scraper):
    meta = Meta(
        title="Warwick District Council",
        url="https://www.warwickdc.gov.uk",
        lads=("E07000222",),
        cases={
            "Test_001": {"uprn": "100070260258"},
            "Test_002": {"uprn": "100070258568"},
            "Test_003": {"uprn": "100070263501"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{BASE}/{address.need('uprn')}")
        page = soup(r.text)

        collections = []
        infoboxes = page.find_all(
            "div", {"class": "col-xs-12 text-center waste-dates margin-bottom-15"}
        )
        for box in infoboxes:
            items = box.find_all("p")
            waste_type = items[0].text.strip().split(" ")[0].strip()
            dates = [_parse_date(item.text).date() for item in items[1:]]
            for day in dates:
                collections.append(Collection(day, waste_type))

        return collections


SCRAPER = Warwick()
