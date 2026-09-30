"""Shropshire: fetches a property's bin schedule from the council's UPRN page."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

API_URL = "https://bins.shropshire.gov.uk/property/{uprn}"


class Shropshire(Scraper):
    meta = Meta(
        title="Shropshire Council",
        url="https://shropshire.gov.uk",
        lads=("E06000051",),
        cases={
            "100070056686": {"uprn": "100070056686"},
            "200000119191": {"uprn": "200000119191"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        page = await http.get(API_URL.format(uprn=address.need("uprn")))
        page_soup = soup(page.text)

        sections = (
            page_soup.find("div", {"class": "container results-table-wrapper"})
            .find("tbody")
            .find_all("tr")
        )

        collections = []
        for item in sections:
            words = item.find_next("a").text.split()[:-1]
            bin_type = " ".join(words).capitalize()
            day_text = (
                item.find("td", {"class": "next-service"})
                .find_next("span")
                .next_sibling.strip()
            )
            collections.append(
                Collection(datetime.strptime(day_text, "%d/%m/%Y").date(), bin_type)
            )

        return collections


SCRAPER = Shropshire()
