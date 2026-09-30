"""Carmarthenshire: fetches bin collection dates from its UPRN-based Umbraco endpoint."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup, text_of


class Carmarthenshire(Scraper):
    meta = Meta(
        title="Carmarthenshire",
        url="https://www.carmarthenshire.gov.wales",
        lads=("W06000010",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        url = (
            "https://www.carmarthenshire.gov.wales/umbraco/Surface/SurfaceRecycling/"
            f"Index/?uprn={uprn}&lang=en-GB"
        )
        response = await http.get(url)
        page = soup(response.content)

        collections: list[Collection] = []
        for container in page.find_all(class_="bin-day-container"):
            bin_type = container.get("class")[1]
            date_tag = container.find(class_="font11 text-center")
            collection_date = text_of(date_tag)
            if not collection_date:
                continue

            try:
                day = datetime.strptime(collection_date, "%A %d/%m/%Y").date()
            except ValueError:
                continue
            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Carmarthenshire()
