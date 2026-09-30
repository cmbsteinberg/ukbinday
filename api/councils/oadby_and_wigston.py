"""Oadby and Wigston: search the address list, then fetch and parse its collection dates."""

from __future__ import annotations

from datetime import date, timedelta

from dateutil.parser import parse

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
)

API_URL = "https://my.oadby-wigston.gov.uk/my-property-finder"
SEARCH_URL = "https://my.oadby-wigston.gov.uk/data/ac/addresses.json"


def _parse_date(date_str: str) -> date:
    if date_str.lower() == "today":
        return date.today()
    if date_str.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return parse(date_str).date()


class OadbyAndWigston(Scraper):
    meta = Meta(
        title="Oadby and Wigston Council",
        url="https://www.oadby-wigston.gov.uk",
        lads=("E07000135",),
        cases={
            "111, Main Street, Swithland": {
                "address": "56, Sussex Road, Wigston, Leicestershire",
            },
            "2, The Banks, Sileby": {
                "address": "89, Leicester Road, Leicester, Leicestershire",
            },
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if address.house_number and address.street:
            address_search = f"{address.house_number}, {address.street}"
        else:
            address_search = address.label or address.first_line
        if not address_search:
            raise InputError("An address is required")

        r = await http.get(SEARCH_URL, params={"term": address_search})
        data = r.json()
        if not data:
            raise AddressNotFound(f"No address found for search term: {address_search}")

        match = match_address(
            address,
            data,
            text=lambda item: item["label"],
            uprn=lambda item: item["value"].removeprefix("ow"),
        )
        address_id = match["value"]

        r = await http.get(API_URL, params={"address_id": address_id})
        collection_panel = soup(r.text).find("div", {"class": "refusecollectiondates"})
        if not collection_panel:
            raise UpstreamError("Oadby and Wigston collection panel was not found")

        collections = []
        for li in collection_panel.select("li"):
            date_tag = li.find("strong")
            if not date_tag:
                continue
            date_str = date_tag.text.strip()
            waste_type_tag = date_tag.find_next("a")
            if not waste_type_tag:
                continue
            waste_type = waste_type_tag.text.strip()
            collections.append(Collection(_parse_date(date_str), waste_type))

        return collections


SCRAPER = OadbyAndWigston()
