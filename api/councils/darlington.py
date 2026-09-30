"""Darlington: looks up collection dates by UPRN on its collection-day page."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

PAGE = "https://www.darlington.gov.uk/bins-waste-and-recycling/collection-day-lookup/"


class Darlington(Scraper):
    meta = Meta(
        title="Darlington Borough Council",
        url=PAGE,
        lads=("E06000005",),
        cases={
            "10013321444": {"uprn": "10013321444"},
            "10013315817": {"uprn": "10013315817"},
            "100110560916": {"uprn": "100110560916"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(PAGE, params={"uprn": address.need("uprn")})
        page = soup(r.text)

        entries = []
        cards = page.select("div.refuse-results")

        for card in cards:
            date_element = card.select_one(".collectionDate p")
            if not date_element:
                continue

            date_str = date_element.get_text(strip=True).split("(")[0].strip()
            collection_date = datetime.strptime(date_str, "%A %d %B %Y").date()
            waste_types = [
                x.get_text(strip=True) for x in card.select(".collection-result-text")
            ]

            for waste_type in waste_types:
                entries.append(Collection(date=collection_date, type=waste_type))

        return entries


SCRAPER = Darlington()
