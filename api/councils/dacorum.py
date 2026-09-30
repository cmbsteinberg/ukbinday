"""Dacorum: submit a postcode to the bin-collection form, select its UPRN, then parse the schedules."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup, Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
    text_of,
)

_API_URL = "https://webapps.dacorum.gov.uk/bincollections/"
_FORM_ARG_IDS = (
    "__VIEWSTATE",
    "__EVENTVALIDATION",
    "btnFindAddr",
    "txtBxPCode",
    "lstBxAddrList",
    "MainContent_btnGetSchedules",
)


def _get_form_args(page: BeautifulSoup) -> dict[str, Any]:
    return {
        element.get("name"): element.get("value")
        for element in page.find_all(["input", "select"])
        if element.get("id") in _FORM_ARG_IDS
    }


def _option_uprn(option: Tag) -> str | None:
    value = option.get("value", "")
    if not isinstance(value, str):
        return None
    parts = value.split(";")
    return parts[1] if len(parts) == 2 else None


def _address_options(select_element: Tag) -> list[Tag]:
    return [
        child
        for child in select_element.children
        if isinstance(child, Tag) and _option_uprn(child) is not None
    ]


class Dacorum(Scraper):
    meta = Meta(
        title="Dacorum Borough Council",
        url="https://www.dacorum.gov.uk/",
        lads=("E07000096",),
        cases={
            "Test_001": {"postcode": "HP1 1AB", "uprn": "200004054631"},
            "Test_002": {"postcode": "HP4 2EZ", "uprn": "100081111531"},
            "Test_003": {"postcode": "HP23 6BE", "uprn": "100080716575"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    transport = __import__("api.councils._base", fromlist=["Transport"]).Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL)
        page = soup(r.text)
        postcode_input = page.find(id="txtBxPCode")
        if not isinstance(postcode_input, Tag):
            raise UpstreamError("Dacorum postcode input was not found")

        postcode_input["value"] = address.need("postcode")
        r = await http.post(_API_URL, data=_get_form_args(page))
        page = soup(r.text)
        address_input = page.find(id="lstBxAddrList")
        if not isinstance(address_input, Tag):
            raise UpstreamError("Dacorum address list was not found")

        options = _address_options(address_input)
        selected = match_address(
            address,
            options,
            text=text_of,
            uprn=_option_uprn,
        )
        address_input["value"] = selected.get("value", "")

        r = await http.post(_API_URL, data=_get_form_args(page))
        page = soup(r.text)
        collection_content = page.find("div", id="MainContent_updPnl")
        if not isinstance(collection_content, Tag):
            raise UpstreamError("Dacorum collection schedule was not found")

        collections: list[Collection] = []
        for entry in collection_content.find_all("div", recursive=False):
            for strong in entry.find_all("strong"):
                bin_type = strong.get_text(strip=True)
                if "bin" not in bin_type.lower():
                    continue

                parent = strong.find_parent("div")
                if parent is None:
                    continue
                date_cell = parent.find_next(
                    "div", string=lambda text: text and "Next collection on" in text
                )
                if date_cell is None:
                    continue
                date_value = date_cell.find_next("div")
                if date_value is None:
                    continue

                try:
                    day = datetime.strptime(
                        date_value.get_text(strip=True), "%a, %d %b %Y"
                    ).date()
                except ValueError:
                    continue
                collections.append(Collection(day, bin_type))
                break

        return collections


SCRAPER = Dacorum()
