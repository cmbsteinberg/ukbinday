"""Bromsgrove: POST the UPRN to its bin-collections page and verify the returned postcode."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    soup,
    text_of,
)

_COLLECTION_URL = "https://bincollections.bromsgrove.gov.uk/BinCollections/Details/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36",
}


class Bromsgrove(Scraper):
    meta = Meta(
        title="Bromsgrove City Council",
        url="https://bromsgrove.gov.uk",
        lads=("E07000234",),
        cases={
            "Shakespeare House": {"uprn": "10094552413", "postcode": "B61 8DA"},
            "The Lodge": {"uprn": "10000218025", "postcode": "B60 2AA"},
            "Ceader Lodge": {"uprn": "100120576392", "postcode": "B60 2JS"},
        },
    )
    requires = frozenset({"uprn", "postcode"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        postcode = "".join(address.need("postcode").split()).upper()

        response = await http.post(_COLLECTION_URL, data={"UPRN": uprn})
        page = soup(response.text)

        returned_postcode = "".join(text_of(page.find("h3")).split()[-2:]).upper()
        bin_info: list[tuple[str, list[datetime.date]]] = []

        for bin_container in page.find_all(class_="collection-container"):
            bin_name = text_of(bin_container.find(class_="heading")).strip()
            collection_dates = []
            for detail in bin_container.find_all(class_="caption"):
                date_string = " ".join(text_of(detail).split()[-3:])
                collection_dates.append(datetime.strptime(date_string, "%d %B %Y").date())
            bin_info.append((bin_name, collection_dates))

        entries = []
        if returned_postcode == postcode:
            for bin_name, collection_dates in bin_info:
                entries.append(Collection(collection_dates[0], bin_name))

        if not entries:
            raise InputError("Could not get collections for the given combination of UPRN and Postcode.")

        return entries


SCRAPER = Bromsgrove()
