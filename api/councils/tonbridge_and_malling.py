"""Tonbridge and Malling: search the postcode form, select the property, then read its collection table."""

from __future__ import annotations

from datetime import datetime

from bs4 import Tag
from dateutil import parser as dateutil_parser

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    find_tag,
    match_address,
    soup,
    text_of,
)

_FORM_URL = "https://www.tmbc.gov.uk/xfp/form/167"
_POSTCODE_FIELD = "q752eec300b2ffef2757e4536b77b07061842041a_0_0"
_ADDRESS_FIELD = "q752eec300b2ffef2757e4536b77b07061842041a_1_0"


class TonbridgeAndMalling(Scraper):
    meta = Meta(
        title="Tonbridge and Malling Borough Council",
        url="https://www.tmbc.gov.uk/bins-waste",
        lads=("E07000115",),
        cases={
            "High Street, West Malling": {
                "postcode": "ME19 6NE",
                "house_number": "138",
                "street": "High Street",
            },
            "Nutfields, Ightham, Sevenoaks": {
                "postcode": "TN15 9EA",
                "house_number": "5",
                "street": "Nutfields",
            },
        },
    )
    requires = frozenset({"postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        form_data: dict[str, object] = {
            _POSTCODE_FIELD: address.need("postcode"),
            "page": 128,
        }
        address_lookup = await http.post(_FORM_URL, data=form_data)
        options = [
            option
            for option in soup(address_lookup.text).find_all("option")
            if isinstance(option, Tag)
            and isinstance(option.get("value"), str)
            and "..." not in option["value"]
        ]
        selected = match_address(address, options, text=text_of)
        selected_id = selected["value"]

        form_data[_ADDRESS_FIELD] = (None, selected_id)
        form_data["next"] = (None, "Next")
        collection_lookup = await http.post(_FORM_URL, data=form_data)

        table = find_tag(soup(collection_lookup.text), "table", class_="waste-collections-table", what="Tonbridge and Malling's collection table was not found")
        tbody = find_tag(table, "tbody", what="Tonbridge and Malling's collection table has no body")

        collections: list[Collection] = []
        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            collection_container = find_tag(cells[1], "div", class_="collections", what="Tonbridge and Malling's collection row has no bins")

            day = dateutil_parser.parse(cells[0].get_text().strip(), dayfirst=True).date()
            if datetime.now().month == 12 and day.month in (1, 2):
                day = day.replace(year=day.year + 1)

            for bin_node in collection_container.find_all("p"):
                collections.append(Collection(day, bin_node.get_text().strip()))

        return collections


SCRAPER = TonbridgeAndMalling()
