"""Salford: fetches the bin-collection page for a UPRN and parses its listed dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    find_tag,
    soup,
)

_URL = "https://www.salford.gov.uk/bins-and-recycling/bin-collection-days/your-bin-collections/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    )
}


class Salford(Scraper):
    meta = Meta(
        title="Salford City Council",
        url="https://www.salford.gov.uk",
        lads=("E08000006",),
        cases={"domestic": {"uprn": "100011404886"}},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_URL, params={"UPRN": address.need("uprn")})

        results = soup(r.text).find_all("div", {"class": "col-12 col-lg-6"})
        collections: list[Collection] = []

        for result in results:
            dates = [item.text for item in result.find_all("li")]
            collection_type = find_tag(result, "strong").text.replace(":", "")
            for current_date in dates:
                day = datetime.strptime(current_date, "%A %d %B %Y").date()
                collections.append(Collection(date=day, type=collection_type))

        return collections


SCRAPER = Salford()
