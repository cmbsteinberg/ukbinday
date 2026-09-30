"""Westmorland and Furness: resolve a UPRN by postcode when needed, then read its collection schedule."""

from __future__ import annotations

from datetime import datetime

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
    soup,
    text_of,
)

_BASE_URL = (
    "https://www.westmorlandandfurness.gov.uk/"
    "bins-recycling-and-street-cleaning/waste-collection-schedule"
)


async def _resolve_uprn(address: Address, http: Http) -> str:
    """Resolve a UPRN via postcode search if one was not provided."""
    if address.uprn:
        return address.uprn

    if not address.postcode:
        raise InputError("Provide a postcode or UPRN.")

    response = await http.get(
        f"{_BASE_URL}/find",
        params={"postcode": address.postcode},
        timeout=30,
    )
    page = soup(response.text)
    select_el = page.find("select", {"name": "uprn"})
    if not isinstance(select_el, Tag):
        raise AddressNotFound(f"No addresses found for postcode: {address.postcode}")

    options = [
        option
        for option in select_el.find_all("option")
        if isinstance(option, Tag) and option.get("value")
    ]
    if not options:
        raise AddressNotFound(f"No addresses found for postcode: {address.postcode}")

    try:
        selected = match_address(
            address,
            options,
            text=text_of,
            uprn=lambda option: option.get("value"),
        )
    except AddressNotFound:
        # The old lookup uses the first result when the supplied house number
        # does not identify an option.
        selected = options[0]

    return str(selected["value"])


class WestmorlandAndFurness(Scraper):
    meta = Meta(
        title="Westmorland and Furness",
        url="https://www.westmorlandandfurness.gov.uk/",
        lads=("E06000064",),
        cases={},
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = await _resolve_uprn(address, http)
        response = await http.get(f"{_BASE_URL}/view/{uprn}", timeout=30)

        page = soup(response.text)
        schedule = page.find_all("div", {"class": "waste-collection__month"})
        now = datetime.now()
        collections: list[Collection] = []

        for month in schedule:
            month_number = datetime.strptime(text_of(month.find("h3")), "%B").month
            collection_days = month.find_all(
                "li", {"class": "waste-collection__day"}
            )
            for collection_day in collection_days:
                day_text = text_of(
                    collection_day.find("span", {"class": "waste-collection__day--day"})
                )
                collection_date = datetime.strptime(day_text, "%d").replace(
                    month=month_number
                )
                bin_type = text_of(
                    collection_day.find(
                        "span", {"class": "waste-collection__day--type"}
                    )
                )

                # The calendar shows the next 12 months, so a month stepping
                # back in time is treated as belonging to the following year.
                year = now.year + (1 if collection_date.month < now.month else 0)
                collection_date = collection_date.replace(year=year)
                collections.append(
                    Collection(collection_date.date(), bin_type)
                )

        return collections


SCRAPER = WestmorlandAndFurness()
