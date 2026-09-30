"""Lisburn and Castlereagh: search by postcode, match a listed address, then fetch its calendar."""

from __future__ import annotations

from datetime import date, datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    match_address,
    soup,
)

_BASE_URL = "https://lisburn.isl-fusion.com"


class LisburnAndCastlereagh(Scraper):
    meta = Meta(
        title="Lisburn and Castlereagh",
        url=_BASE_URL,
        lads=("N09000007",),
        cases={},
    )
    requires = frozenset({"postcode", "house_number"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        house_number = address.need("house_number")

        response = await http.get(f"{_BASE_URL}/address/{postcode}")
        address_list = response.json()["html"]
        page = soup(address_list)

        candidates: list[tuple[str, str]] = []
        for li in page.find_all("li"):
            links = li.find_all("a")
            if not links:
                continue
            link = links[0]
            href = link.get("href")
            if not isinstance(href, str):
                continue
            property_id = href.replace("/view/", "").replace("/", "")
            candidates.append((link.get_text(), property_id))

        selected = match_address(address, candidates, text=lambda candidate: candidate[0])
        if not selected[1]:
            raise AddressNotFound(f"Lisburn and Castlereagh has no property for house number {house_number}")

        today = date.today()
        calendar_url = f"{_BASE_URL}/calendar/{selected[1]}/{today.strftime('%Y-%m-%d')}"
        calendar_data = (await http.get(calendar_url)).json()
        next_collections = calendar_data["nextCollections"]

        collections: list[Collection] = []
        for collection in next_collections["collections"].values():
            collection_date = datetime.strptime(collection["date"], "%Y-%m-%d").date()
            for item in collection["collections"].values():
                collections.append(Collection(collection_date, item["name"]))

        return collections


SCRAPER = LisburnAndCastlereagh()
