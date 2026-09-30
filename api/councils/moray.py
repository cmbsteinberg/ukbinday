"""Moray: postcode lookup resolves an internal property ID, then an annual calendar lists collections."""

from __future__ import annotations

import re
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

_BASE = "https://bindayfinder.moray.gov.uk"
_BIN_TYPE_MAP = {
    "B": "Brown Bin",
    "O": "Glass Container",
    "G": "Green Bin",
    "P": "Purple Bin",
    "C": "Blue Bin",
}
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _property_id(link: Tag) -> str:
    href = str(link.get("href", ""))
    match = re.search(r"id=(\d+)", href)
    if match is None:
        raise ValueError(f"Moray property link has no ID: {href}")
    return match.group(1)


class Moray(Scraper):
    meta = Meta(
        title="Moray",
        url="https://bindayfinder.moray.gov.uk/",
        lads=("S12000020",),
        cases={},
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        property_id: str | None = None

        if address.postcode:
            response = await http.get(
                f"{_BASE}/refuse_roads.php",
                params={"pcode": address.postcode},
                timeout=30,
            )
            links = [
                link
                for link in soup(response.text).find_all(
                    "a", href=re.compile(r"disp_bins\.php\?id=")
                )
                if isinstance(link, Tag)
            ]

            if not links:
                raise AddressNotFound(f"No properties found for postcode: {address.postcode}")

            if address.house_number:
                link = match_address(address, links, text=text_of)
            else:
                link = links[0]
            property_id = _property_id(link)
        elif address.uprn:
            # Legacy: Moray accepts its internal property ID as the UPRN.
            property_id = address.uprn.zfill(8)
        else:
            raise InputError("Either postcode or property ID (as UPRN) required")

        property_id = property_id.zfill(8)
        year = datetime.today().year
        response = await http.get(
            f"{_BASE}/cal_{year}_view.php",
            params={"id": property_id},
            timeout=30,
            check=False,
        )
        if response.status_code != 200:
            return []

        page = soup(response.text)
        today = datetime.today().date()
        collections: list[Collection] = []

        for month_container in page.find_all("div", class_="month-container"):
            header = month_container.find("div", class_="month-header")
            heading = header.find("h2") if isinstance(header, Tag) else None
            month_name = text_of(heading)
            if month_name not in _MONTH_NAMES:
                continue
            month_num = _MONTH_NAMES.index(month_name) + 1

            days_container = month_container.find("div", class_="days-container")
            if not isinstance(days_container, Tag):
                continue

            for day_div in days_container.find_all("div"):
                css_classes = day_div.get("class", [])
                if "blank" in css_classes:
                    continue

                day_text = day_div.get_text(strip=True)
                if not day_text or not day_text.isdigit():
                    continue
                day_num = int(day_text)

                for css_class in css_classes:
                    if css_class in ("blank", "day-name", ""):
                        continue

                    for char in css_class:
                        if char not in _BIN_TYPE_MAP:
                            continue
                        try:
                            collection_date = datetime(year, month_num, day_num).date()
                        except ValueError:
                            continue
                        if collection_date >= today:
                            collections.append(
                                Collection(collection_date, _BIN_TYPE_MAP[char])
                            )

        return collections


SCRAPER = Moray()
