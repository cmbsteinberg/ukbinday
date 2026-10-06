"""Stockport: fetches a property's bin collections from its UPRN-specific page."""

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

_URL = "https://myaccount.stockport.gov.uk/bin-collections/show"
_DATE_PATTERN = re.compile(r"(?:\w+,\s*)?(\d{1,2}\s+\w+\s+\d{4})", re.IGNORECASE)


class Stockport(Scraper):
    meta = Meta(
        title="Stockport Council",
        url="https://stockport.gov.uk",
        lads=("E08000007",),
        cases={"domestic": {"uprn": "100011460157"}},
    )
    requires = frozenset({"uprn"})
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/137.0 Safari/537.36"
        )
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{_URL}/{address.need('uprn')}", timeout=30)
        page = soup(r.text)

        bins = page.find_all("div", {"class": re.compile(r"service-item")})
        collections = []
        for bin_div in bins:
            h3 = bin_div.find("h3")
            if not h3:
                continue

            bin_name = h3.get_text(strip=True)
            if "bin" not in bin_name.lower():
                continue

            bin_name = bin_name.capitalize()
            date_match = _DATE_PATTERN.search(bin_div.get_text())

            if date_match:  # a bin with no date has no upcoming collection
                collections.append(Collection(parse_date(date_match.group(1)), bin_name))

        return collections


SCRAPER = Stockport()
