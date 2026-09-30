"""North Kesteven: fetches the UPRN-specific bin schedule from its display page."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_URL = "https://www.n-kesteven.org.uk/bins/display"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)


class NorthKesteven(Scraper):
    meta = Meta(
        title="North Kesteven",
        url="https://www.n-kesteven.org.uk",
        lads=("E07000139",),
        cases={},
    )
    requires = frozenset({"uprn"})
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(
            f"{_URL}?uprn={address.need('uprn')}",
            timeout=30,
        )
        page = soup(response.text)
        bin_dates_div = page.find("div", {"class": "bin-dates"})
        if not bin_dates_div:
            return []

        collections: list[Collection] = []
        for li in bin_dates_div.find_all("li", {"class": "text-large"}):
            bin_type_span = li.find("span", {"class": "font-weight-bold"})
            if not bin_type_span:
                continue

            bin_type = bin_type_span.get_text(strip=True)
            date_strong = li.find("strong")
            if not date_strong:
                continue

            date_text = date_strong.get_text(strip=True)
            try:
                collection_date = datetime.strptime(date_text, "%A, %d %B %Y").date()
                full_text = li.get_text(strip=True)
                match = re.search(
                    rf"{re.escape(bin_type)}\s+(.*?)\s+bin on",
                    full_text,
                )
                if match:
                    bin_description = match.group(1).strip()
                    if bin_description:
                        bin_type = f"{bin_type} {bin_description}"

                collections.append(Collection(collection_date, bin_type))
            except ValueError:
                continue

        return collections


SCRAPER = NorthKesteven()
