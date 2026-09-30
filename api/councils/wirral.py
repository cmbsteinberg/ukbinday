"""Wirral: fetches the collection schedule from the property's UPRN page."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    soup,
)

VIEW_URL = "https://www.wirral.gov.uk/bins-and-recycling/bin-collection-dates/view/{}"


class Wirral(Scraper):
    meta = Meta(
        title="Wirral Council",
        url="https://www.wirral.gov.uk/bins-and-recycling/bin-collection-dates",
        lads=("E08000015",),
        cases={
            "Elm Avenue, Upton": {
                "postcode": "CH49 4NP",
                "uprn": "42037487",
            },
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").strip().lstrip("0")
        r = await http.get(VIEW_URL.format(uprn), timeout=30)
        page = soup(r.text)

        entries = []
        for day in page.select("li.waste-collection__day"):
            time_el = day.select_one("time")
            type_el = day.select_one(".waste-collection__day--type")
            if not time_el or not type_el:
                continue
            bin_type = type_el.get_text(strip=True)
            entries.append(
                Collection(
                    date=datetime.strptime(time_el["datetime"], "%d-%m-%Y").date(),
                    type=bin_type,
                )
            )

        if not entries:
            raise AddressNotFound(f"Wirral has no bin schedule for UPRN {uprn}")

        return entries


SCRAPER = Wirral()
