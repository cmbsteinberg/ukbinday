"""Teignbridge: fetches a property's collection dates from its UPRN-based bin finder."""

from __future__ import annotations

from datetime import datetime

from bs4 import Tag

from api.councils._base import Address, Collection, Http, Meta, Scraper, Transport, soup

_BIN_URL = "https://www.teignbridge.gov.uk/repositories/hidden-pages/bin-finder"


class Teignbridge(Scraper):
    meta = Meta(
        title="Teignbridge District Council",
        url="https://www.teignbridge.gov.uk",
        lads=("E07000045",),
        cases={
            "EX4 2JR": {"postcode": "EX4 2JR", "uprn": "10032968474"},
            "TQ12": {"postcode": "TQ12 4QQ", "uprn": "100040270498"},
        },
    )
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_BIN_URL, params={"uprn": address.need("uprn")})
        page = soup(r.text)
        collections: list[Collection] = []

        for heading in page.find_all("h3", class_="binCollectionH3"):
            date_text = heading.get_text(strip=True)
            span = heading.find("span", class_="binDayDescriptor")
            if isinstance(span, Tag):
                day_name = span.get_text(strip=True)
                date_text = date_text.replace(day_name, "").strip()

            try:
                collection_date = datetime.strptime(date_text, "%d %B %Y").date()
            except ValueError:
                continue

            container = heading.find_next_sibling("div", class_="binInfoContainer")
            if not isinstance(container, Tag):
                continue

            for line in container.find_all("div", class_="binInfoLine"):
                image = line.find("img")
                if isinstance(image, Tag) and image.get("title"):
                    collections.append(Collection(collection_date, str(image["title"])))

        return collections


SCRAPER = Teignbridge()
