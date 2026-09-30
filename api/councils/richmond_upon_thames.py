"""Richmond upon Thames: looks up the next collections for a property by UPRN."""

from __future__ import annotations

from datetime import datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    soup,
)

_API_URL = "https://www.richmond.gov.uk/my_richmond"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_ALLOWED_SERVICES = {
    "Glass, can, plastic and carton recycling",
    "Paper and card recycling",
    "Rubbish and food",
    "Garden waste",
}


class RichmondUponThames(Scraper):
    meta = Meta(
        title="London Borough of Richmond upon Thames",
        url="https://www.richmond.gov.uk/",
        lads=("E09000027",),
        cases={
            "Sheen Common Drive": {"uprn": "100022316011"},
            "Rosemont Road": {"uprn": "100022315214"},
            "Bryanston Avenue": {"uprn": "100022330653"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        response = await http.get(_API_URL, params={"pid": uprn}, timeout=30)

        page = soup(response.text)
        waste_div = page.find("div", class_="my-waste")
        if not isinstance(waste_div, Tag):
            raise AddressNotFound(f"No waste collections found for UPRN {uprn}")

        collections: list[Collection] = []
        for heading in waste_div.find_all("h4"):
            service_name = heading.get_text(strip=True)
            if service_name not in _ALLOWED_SERVICES:
                continue

            ul_sibling = heading.find_next_sibling("ul")
            if not isinstance(ul_sibling, Tag):
                continue

            item = ul_sibling.find("li")
            if not isinstance(item, Tag):
                continue

            for link in item.find_all("a"):
                link.decompose()

            item_text = item.get_text(strip=True)
            if "No collection contract" in item_text or not item_text:
                continue

            try:
                date_parts = item_text.split()
                if len(date_parts) < 3:
                    continue
                date_str = " ".join(date_parts[-3:])
                collection_date = datetime.strptime(date_str, "%d %B %Y").date()
            except (ValueError, IndexError):
                continue

            collections.append(Collection(collection_date, service_name))

        return collections


SCRAPER = RichmondUponThames()
