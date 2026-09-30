"""Cheshire East: fetches the bin schedule from its UPRN-based collection-day endpoint."""

from __future__ import annotations

from datetime import datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    soup,
)

PAGE = "https://online.cheshireeast.gov.uk/mycollectionday"
API = "https://online.cheshireeast.gov.uk/MyCollectionDay/SearchByAjax/GetBartecJobList"


class CheshireEast(Scraper):
    meta = Meta(
        title="Cheshire East",
        url=PAGE,
        lads=("E06000049",),
        cases={},
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if uprn:
            url = f"{API}?uprn={uprn}"
        else:
            # Retain the legacy URL fallback for callers that stored a direct URL.
            url = address.need("url")

        response = await http.get(url)
        page = soup(response.text)
        table = page.find("table", {"class": "job-details"})

        collections: list[Collection] = []
        if isinstance(table, Tag):
            for row in table.find_all("tr", {"class": "data-row"}):
                cells = row.find_all(
                    "td",
                    {
                        "class": lambda value: isinstance(value, str)
                        and value.startswith("visible-cell")
                    },
                )
                labels = cells[0].find_all("label") if cells else []
                if len(labels) < 3:
                    continue

                bin_type = labels[2].get_text(strip=True)
                date_text = labels[1].get_text(strip=True)
                if not bin_type or not date_text:
                    continue

                try:
                    if "-" in date_text:
                        day = datetime.strptime(date_text, "%Y-%m-%d").date()
                    elif "/" in date_text:
                        day = datetime.strptime(date_text, "%d/%m/%Y").date()
                    else:
                        continue
                except ValueError:
                    continue

                collections.append(Collection(day, bin_type))

        return collections


SCRAPER = CheshireEast()
