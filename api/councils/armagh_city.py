"""Armagh City, Banbridge and Craigavon: fetches bin dates from the result page using the UPRN."""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_URL = "https://www.armaghbanbridgecraigavon.gov.uk/"
_RESULT_URL = "https://www.armaghbanbridgecraigavon.gov.uk/resident/binday-result/?address={uprn}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _extract_bin_schedule(page: BeautifulSoup, heading_class: str) -> list[str]:
    section_heading = page.find("div", class_=heading_class)
    if section_heading is None:
        return []
    content_col = section_heading.find_next("div", class_="col-sm-12 col-md-9")
    if content_col is None:
        return []

    dates = []
    for heading in content_col.find_all("h4"):
        match = re.search(r"\d{2}/\d{2}/\d{4}", heading.get_text(strip=True))
        if match:
            dates.append(match.group(0))
    return dates


class ArmaghCity(Scraper):
    meta = Meta(
        title="Armagh City, Banbridge and Craigavon",
        url=_URL,
        lads=("N09000002",),
        cases={},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(_RESULT_URL.format(uprn=address.need("uprn")), timeout=30)
        page = soup(response.text)

        collections = []
        for heading_class, bin_type in (
            ("heading bg-black", "Domestic"),
            ("heading bg-green", "Recycling"),
            ("heading bg-brown", "Garden"),
        ):
            for collection_date in _extract_bin_schedule(page, heading_class):
                try:
                    day = datetime.strptime(collection_date, "%d/%m/%Y").date()
                except ValueError:
                    continue
                collections.append(Collection(day, bin_type))
        if not collections:
            raise UpstreamError("Armagh City: no collection sections found in result page")
        return collections


SCRAPER = ArmaghCity()
