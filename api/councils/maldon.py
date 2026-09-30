"""Maldon: looks up collections from the Suez service using the property's UPRN."""

from __future__ import annotations

import re
from datetime import date, datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    soup,
    text_of,
)

_TITLE = "Maldon District Council"
_API_URL = "https://maldon.suez.co.uk/maldon/ServiceSummary?uprn="


def _extract_dates(text: str) -> list[date]:
    return [
        datetime.strptime(value, "%d/%m/%Y").date()
        for value in re.findall(r"\d{2}/\d{2}/\d{4}", text)
    ]


class Maldon(Scraper):
    meta = Meta(
        title=_TITLE,
        url="https://www.maldon.gov.uk/",
        lads=("E07000074",),
        cases={
            "test 1": {"uprn": "200000917928"},
            "test 2": {"uprn": "100091258454"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{_API_URL}{address.need('uprn')}")
        collections = soup(r.text).find_all("div", {"class": "panel-default"})

        if not collections:
            raise AddressNotFound(f"No collections found for UPRN {address.uprn}")

        entries = []
        for collection in collections:
            title = text_of(collection.find("h2", {"class": "panel-title"}))
            collection_text = collection.get_text()

            if title == "Other Services" or "You are not currently subscribed" in collection_text:
                continue

            for day in _extract_dates(collection_text):
                entries.append(Collection(date=day, type=title))

        return entries


SCRAPER = Maldon()
