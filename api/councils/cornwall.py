"""Cornwall: resolve a property by UPRN or postcode, then fetch its collection days."""

from __future__ import annotations

from datetime import date, datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
    match_address,
    soup,
    text_of,
)

_SEARCH_URLS = {
    "uprn_search": "https://www.cornwall.gov.uk/my-area/",
    "collection_search": "https://www.cornwall.gov.uk/umbraco/Surface/Waste/MyCollectionDays?subscribe=False",
}


class Cornwall(Scraper):
    meta = Meta(
        title="Cornwall Council",
        url="https://cornwall.gov.uk",
        lads=("E06000052",),
        cases={
            "known_uprn": {"uprn": "100040118005"},
            "unknown_uprn": {"postcode": "TR26 1SP", "house_number": "7"},
            "unknown_uprn_int": {"postcode": "PL17 8PL", "house_number": "3"},
        },
    )
    requires = frozenset()
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if uprn is None:
            if address.postcode is None or address.house_number is None:
                raise InputError("Cornwall needs a UPRN or a postcode and house number")

            r = await http.get(
                _SEARCH_URLS["uprn_search"],
                params={"Postcode": address.postcode},
            )
            options = soup(r.text).select("#Uprn option")
            if not options:
                raise AddressNotFound(f"No properties found for postcode {address.postcode}")

            selected = match_address(
                address,
                options,
                text=text_of,
                uprn=lambda option: option.get("value"),
            )
            uprn = selected.get("value")
            if not uprn:
                raise AddressNotFound(f"No UPRN found for {address.first_line or address.postcode}")

        r = await http.get(
            _SEARCH_URLS["collection_search"],
            params={"uprn": uprn},
        )
        collections = []
        for collection_div in soup(r.text).find_all("div", class_="collection"):
            spans = collection_div.find_all("span")
            if not spans:
                continue
            collection = spans[0].get_text()
            day = spans[-1].get_text() + " " + str(date.today().year)
            collections.append(
                Collection(datetime.strptime(day, "%d %b %Y").date(), collection)
            )

        return collections


SCRAPER = Cornwall()
