"""Redditch: POST the UPRN to the council's bin-collections page and parse its HTML."""

from __future__ import annotations

from datetime import datetime

from bs4 import Tag

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_URI = "https://bincollections.redditchbc.gov.uk/BinCollections/Details"


class Redditch(Scraper):
    meta = Meta(
        title="Redditch",
        url="https://redditchbc.gov.uk",
        lads=("E07000236",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.post(_URI, data={"UPRN": address.need("uprn")})
        page = soup(response.content)
        collections: list[Collection] = []

        for container in page.find_all("div", class_="collection-container"):
            image = container.find("img")
            caption = container.find("p", class_="caption")
            if not isinstance(image, Tag) or not isinstance(caption, Tag):
                continue

            bin_type = image.get("alt")
            if not isinstance(bin_type, str):
                continue

            next_collection = caption.text.replace("Next collection ", "").strip()
            try:
                day = datetime.strptime(next_collection, "%A, %d %B %Y").date()
            except ValueError:
                continue
            collections.append(Collection(day, bin_type))

            for item in container.find_all("li"):
                try:
                    day = datetime.strptime(item.text.strip(), "%A, %d %B %Y").date()
                except ValueError:
                    continue
                collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Redditch()
