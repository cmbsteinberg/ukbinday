"""Tamworth: sends the UPRN to Lichfield's bin-collection page and parses its HTML schedule."""

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

_PAGE = "https://www.lichfielddc.gov.uk/homepage/6/bin-collection-dates"
_HEADERS = {
    "Origin": "https://www.lichfielddc.gov.uk",
    "Referer": "https://www.lichfielddc.gov.uk",
    "User-Agent": "Mozilla/5.0",
}


class Tamworth(Scraper):
    meta = Meta(
        title="Tamworth Borough",
        url="https://www.tamworth.gov.uk",
        lads=("E07000199",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            f"{_PAGE}?uprn={address.need('uprn')}",
            headers=_HEADERS,
        )
        page = soup(r.text)
        bins = page.find_all("h3", class_="bin-collection-tasks__heading")
        dates = page.find_all("p", class_="bin-collection-tasks__date")

        collections: list[Collection] = []
        for i, date_node in enumerate(dates):
            try:
                bin_type = " ".join(text_of(bins[i]).split()[2:4])
                day = parse_date(text_of(date_node))
            except (ValueError, IndexError):
                continue
            collections.append(Collection(day, bin_type))
        return collections


SCRAPER = Tamworth()
