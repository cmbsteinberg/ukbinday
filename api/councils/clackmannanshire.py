"""Clackmannanshire: search a postcode, match a property, then read its iCalendar feeds."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
    parse_ics,
    soup,
    text_of,
)

_BASE_URL = "https://www.clacks.gov.uk"
_SEARCH_URL = f"{_BASE_URL}/environment/wastecollection/"
_YEAR_SUFFIX_RE = re.compile(r"\s*\d{4}\s*$")


async def _find_property_url(address: Address, http: Http) -> str:
    postcode = address.need("postcode")
    response = await http.get(_SEARCH_URL, params={"pc": postcode}, timeout=30)
    page = soup(response.text)

    results_div = page.find("div", {"class": "highlight"})
    links: list[Tag] = []
    if isinstance(results_div, Tag):
        links = [
            link
            for link in results_div.find_all("a")
            if isinstance(link, Tag)
            and str(link.get("href", "")).startswith("/environment/wastecollection/id/")
        ]

    if not links:
        raise AddressNotFound(
            f"No properties were found for postcode {postcode} on the "
            "Clackmannanshire Council website."
        )

    if not (address.house_number or address.street or address.first_line):
        raise InputError("Clackmannanshire needs address text to select a property")

    link = match_address(address, links, text=text_of)
    return urljoin(_BASE_URL, str(link["href"]))


async def _find_ics_links(property_url: str, http: Http) -> list[str]:
    response = await http.get(property_url, timeout=30)
    page = soup(response.text)

    links = [
        urljoin(_BASE_URL, str(link["href"]))
        for link in page.find_all("a")
        if isinstance(link, Tag) and str(link.get("href", "")).lower().endswith(".ics")
    ]
    if not links:
        raise AddressNotFound("No calendar (.ics) links were found for this property.")
    return links


class Clackmannanshire(Scraper):
    meta = Meta(
        title="Clackmannanshire Council",
        url="https://www.clacks.gov.uk",
        lads=("S12000005",),
        cases={
            "16 Crophill, Sauchie": {
                "postcode": "FK10 3EY",
                "house_number": "16",
                "street": "Crophill, Sauchie",
            },
            "Elim Pentecostal Church, Alloa": {
                "postcode": "FK10 1EB",
                "address": "Elim Pentecostal Church, Alloa",
            },
            "With garden waste permit": {
                "postcode": "FK10 3EY",
                "house_number": "16",
                "street": "Crophill, Sauchie",
                "garden_waste": "true",
            },
        },
    )
    requires = frozenset({"postcode"})
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        property_url = await _find_property_url(address, http)
        ics_links = await _find_ics_links(property_url, http)

        response = await http.get(ics_links[0], timeout=30)
        collections = [
            Collection(event.date, event.summary)
            for event in parse_ics(response.text)
        ]

        if address.extra.get("garden_waste") and len(ics_links) > 1:
            response = await http.get(ics_links[1], timeout=30)
            collections.extend(
                Collection(
                    event.date,
                    _YEAR_SUFFIX_RE.sub("", event.summary).strip(),
                )
                for event in parse_ics(response.text)
            )

        return collections


SCRAPER = Clackmannanshire()
