"""Gedling: search by postcode, match an address, then read its next collection dates."""

from __future__ import annotations

from bs4 import BeautifulSoup

from api.councils._base import Collection, Meta, parse_date, text_of
from api.councils._platforms.liberty_create import LibertyCreate, LibertyCreateConfig


def _dated_rows(page: BeautifulSoup) -> list[Collection]:
    """Rows of (service, weekday, date); the service is "Recycling Collection Service"."""
    collections: list[Collection] = []
    for row in page.select("table.listing tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        node = cells[0].select_one("[data-current_value]")  # the cell's text is rendered by script
        if node is None:
            continue
        service = str(node["data-current_value"])
        collections.append(
            Collection(
                date=parse_date(text_of(cells[2])),
                type=service.removesuffix(" Collection Service"),
            )
        )
    return collections


SCRAPER = LibertyCreate(
    Meta(
        title="Gedling",
        url="https://waste.digital.gedling.gov.uk/w/webpage/bin-collections",
        lads=("E07000173",),
        cases={
            "4 Denbury Road": {
                "postcode": "NG15 9FQ",
                "house_number": "4",
                "street": "Denbury Road",
            },
            "2 Orchard Court": {
                "postcode": "NG4 4FF",
                "house_number": "2",
                "street": "Orchard Court",
            },
        },
    ),
    LibertyCreateConfig(
        base_url="https://waste.digital.gedling.gov.uk",
        landing_path="/w/webpage/bin-collections",
        subpage_id="PAG0000634GBSHB1",
        address_field="PCF0014909",
        parse=_dated_rows,
    ),
)
