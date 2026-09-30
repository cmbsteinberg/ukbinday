"""Braintree: submit the postcode to its session-based form, select the matching address, then read collection dates."""

from __future__ import annotations

from datetime import date

from dateutil import parser as date_parser

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    match_address,
    soup,
    text_of,
)

_URL = "https://www.braintree.gov.uk/xfp/form/554"
_POSTCODE_FIELD = "qe15dda0155d237d1ea161004d1839e3369ed4831_0_0"
_ADDRESS_FIELD = "qe15dda0155d237d1ea161004d1839e3369ed4831_1_0"

_NAME_MAP = {
    "Non-recyclable waste(grey bin)": "Grey Bin",
    "Outdoorfood caddy": "Food Bin",
    "Outdoor food caddy": "Food Bin",
    "Mixed recycling(blue-lidded bin)": "Mixed Recycling",
    "Paper and card recycling(red-lidded bin)": "Paper & Card",
    "Garden bin(green bin)": "Garden Bin",
}


def _hidden_inputs(page: object) -> dict[str, str]:
    return {
        str(item["name"]): str(item.get("value", ""))
        for item in page.find_all("input", {"type": "hidden"})
        if item.get("name") and item["name"] != _ADDRESS_FIELD
    }


class Braintree(Scraper):
    meta = Meta(
        title="Braintree District Council",
        url="https://www.braintree.gov.uk",
        lads=("E07000067",),
        cases={
            "30 Boars Tye Road": {"house_number": "30", "postcode": "CM8 3QE"},
            "64 Silver Street": {"house_number": "64", "postcode": "CM8 3QG"},
            "20 Peel Crescent": {"house_number": "20", "postcode": "CM7 2RS"},
        },
    )
    requires = frozenset({"postcode", "house_number"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")

        landing = await http.get(_URL)
        form_data = _hidden_inputs(soup(landing.text))
        form_data[_POSTCODE_FIELD] = postcode

        address_lookup = await http.post(_URL, data=form_data)
        lookup_page = soup(address_lookup.text)
        options = [
            option
            for option in lookup_page.find_all("option")
            if len(option.get("value", "")) > 5
        ]
        if not options:
            raise AddressNotFound(f"No properties listed for {postcode}")

        selected = match_address(address, options, text=text_of)
        form_data = _hidden_inputs(lookup_page)
        form_data[_POSTCODE_FIELD] = postcode
        form_data[_ADDRESS_FIELD] = str(selected["value"])
        form_data["next"] = "Next"

        collection_lookup = await http.post(_URL, data=form_data)
        collections: list[Collection] = []
        for result in soup(collection_lookup.text).find_all("div", class_="date_display"):
            try:
                collection_info = result.get_text().strip().split("\n")
                raw_type = collection_info[0].strip()
                if len(collection_info) < 2:
                    continue
                bin_type = _NAME_MAP.get(raw_type, raw_type)
                collection_date: date = date_parser.parse(
                    collection_info[1].strip(), dayfirst=True
                ).date()
            except (IndexError, TypeError, ValueError):
                continue
            collections.append(Collection(collection_date, bin_type))
        return collections


SCRAPER = Braintree()
