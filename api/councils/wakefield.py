"""Wakefield: looks up collection dates on the where-i-live page using a UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup, text_of

_PAGE = "https://www.wakefield.gov.uk/where-i-live/"
_TYPES = {
    "Household": "Household",
    "Mixed": "Mixed Recycling",
    "Garden": "Garden",
}


class Wakefield(Scraper):
    meta = Meta(
        title="Wakefield Council",
        url="https://wakefield.gov.uk",
        lads=("E08000036",),
        cases={
            "uprn1": {"uprn": "63024087"},
            "uprn2": {"uprn": "63105305"},
            "uprn3": {"uprn": "63012193"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(
            _PAGE,
            params={"uprn": address.need("uprn"), "a": "Your Address"},
        )
        page = soup(response.content)
        collections: list[Collection] = []

        for section in page.select(".tablet\\:l-col-fb-4.u-mt-10"):
            bin_type_raw = text_of(section.find("strong")).split(" ")[0]
            bin_type = _TYPES.get(bin_type_raw)
            if not bin_type:
                continue

            collection_dates = set()
            date_elements = section.select(".u-mb-2")
            date_elements.extend(section.find_all("li"))
            for element in date_elements:
                if ", " not in element.text:
                    continue
                try:
                    date_str = element.text.split(", ")[1].strip()
                    collection_dates.add(datetime.strptime(date_str, "%d %B %Y").date())
                except (ValueError, IndexError):
                    continue

            for collection_date in collection_dates:
                collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Wakefield()
