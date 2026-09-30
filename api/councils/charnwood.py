"""Charnwood: search its address list, then fetch the matched property's collection dates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

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
    parse_date,
    soup,
    text_of,
)

API_URL = "https://my.charnwood.gov.uk/my-property-finder"
SEARCH_URL = "https://my.charnwood.gov.uk/data/ac/addresses.json"


def _parse_date(date_text: str) -> date:
    if date_text.lower() == "today":
        return date.today()
    if date_text.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    return parse_date(date_text)


def _candidate_uprn(candidate: Mapping[str, str]) -> str:
    return candidate["value"].removeprefix("cbc")


class Charnwood(Scraper):
    meta = Meta(
        title="Charnwood",
        url="https://www.charnwood.gov.uk/",
        lads=("E07000130",),
        cases={
            "111, Main Street, Swithland": {"address": "111, Main Street, Swithland"},
            "2, The Banks, Sileby": {"address": "2 The Banks, Sileby"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if address.house_number and address.street:
            search_text = f"{address.house_number}, {address.street}"
        else:
            search_text = address.label or ""

        if not search_text and not (address.uprn and address.postcode):
            raise InputError("Charnwood needs an address, or a UPRN and postcode")

        term = address.postcode if address.uprn and address.postcode else search_text
        r = await http.get(SEARCH_URL, params={"term": term})
        candidates: list[dict[str, str]] = r.json()
        if not candidates:
            raise AddressNotFound(f"No Charnwood address found for {search_text or address.postcode}")

        candidate = match_address(
            address,
            candidates,
            text=lambda item: item["label"],
            uprn=_candidate_uprn,
        )
        address_id = candidate["value"]

        r = await http.get(API_URL, params={"address_id": address_id})
        collection_panel = soup(r.text).find("div", {"class": "refusecollectiondates"})
        if collection_panel is None:
            raise UpstreamError("Charnwood response has no collection panel")

        collections = []
        for li in collection_panel.select("li"):
            date_tag = li.find("strong")
            if date_tag is None:
                continue
            waste_type_tag = date_tag.find_next("a")
            if waste_type_tag is None:
                continue
            collections.append(
                Collection(_parse_date(text_of(date_tag)), text_of(waste_type_tag))
            )
        return collections


SCRAPER = Charnwood()
