"""Exeter: looks up bin collections by UPRN and parses dates from returned HTML."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_URL = "https://exeter.gov.uk/repositories/hidden-pages/address-finder/?qsource=UPRN&qtype=bins&term="
_ORDINALS = re.compile(r"(?<=[0-9])(?:st|nd|rd|th)")


class Exeter(Scraper):
    meta = Meta(
        title="Exeter City Council",
        url="https://exeter.gov.uk/",
        lads=("E07000041",),
        cases={
            "Test_001": {"uprn": "100040227486"},
            "Test_002": {"uprn": "10013043921"},
            "Test_003": {"uprn": "10023120282"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{_URL}{address.need('uprn')}")
        json_data = r.json()[0]["Results"]
        page = soup(json_data)
        bins = page.find_all("h2")
        dates = page.find_all("h3")

        collections = []
        for bin_heading, date_heading in zip(bins, dates, strict=False):
            raw_date = _ORDINALS.sub("", date_heading.get_text(strip=True))
            for fmt in ("%A, %d %B %Y", "%A %d %B %Y"):
                try:
                    day = datetime.strptime(raw_date, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                continue

            collections.append(Collection(day, bin_heading.text.replace(" collection", "")))

        return collections


SCRAPER = Exeter()
