"""Wandsworth: looks up a UPRN on its My Property page and parses upcoming collections."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_API_URL = "https://www.wandsworth.gov.uk/my-property/"


class Wandsworth(Scraper):
    meta = Meta(
        title="Wandsworth Council",
        url="https://www.wandsworth.gov.uk",
        lads=("E09000032",),
        cases={
            "100022659217": {"uprn": "100022659217"},
            "100022611611": {"uprn": "100022611611"},
            "10091501435": {"uprn": "10091501435"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.5",
        "Referer": "https://www.wandsworth.gov.uk",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        if not uprn.isdigit():
            raise InputError("UPRN must be numeric")

        r = await http.get(
            _API_URL,
            params={"UPRN": uprn, "propertyidentified": "Select"},
            timeout=90,
        )
        page = soup(r.text)

        if not page.find("h1", string="My Property"):
            raise UpstreamError("Unexpected page content from Wandsworth Council")

        if not page.find("div", id="result"):
            raise AddressNotFound(
                f"UPRN {uprn} is invalid or outside the Wandsworth Council area"
            )

        rubbish_heading = page.find(
            "h3", string=lambda text: text and "Rubbish and recycling" in text
        )
        if rubbish_heading:
            next_p = rubbish_heading.find_next_sibling("p")
            if next_p and "currently unavailable" in next_p.get_text():
                raise UpstreamError("Wandsworth collection data is currently unavailable")

        collections: list[Collection] = []
        for waste_heading in page.find_all("h4", class_="collection-heading"):
            waste_type = waste_heading.get_text(strip=True)
            waste_collections = waste_heading.find_next_sibling("div", class_="collections")
            if not waste_collections:
                continue

            for collection in waste_collections.find_all("div", class_="collection"):
                strong = collection.find("strong")
                if strong:
                    strong.extract()

                badge = collection.find("span", class_="badge")
                if badge:
                    badge.extract()

                date_str = collection.get_text(strip=True)
                try:
                    collection_date = datetime.strptime(date_str, "%A %d %B %Y").date()
                except ValueError:
                    continue

                collections.append(Collection(collection_date, waste_type))

        if not collections:
            raise AddressNotFound(f"No collections found for UPRN {uprn}")

        return collections


SCRAPER = Wandsworth()
