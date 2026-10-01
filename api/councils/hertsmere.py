"""Hertsmere: search by postcode, match an address, then read its collection weekdays."""

from __future__ import annotations

from bs4 import BeautifulSoup

from api.councils._base import Collection, Meta, next_weekday
from api.councils._platforms.liberty_create import LibertyCreate, LibertyCreateConfig

_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _weekdays(page: BeautifulSoup) -> list[Collection]:
    """Rows of (round, weekday); each round is collected on the next such weekday."""
    table = page.find("table", class_="table listing table-striped")
    tbody = table.find("tbody") if table else None
    if not tbody:
        return []
    collections: list[Collection] = []
    for row in tbody.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        round_type, day_name = cells[0].strip(), cells[1].strip()
        if day_name in _DAYS:
            collections.append(Collection(date=next_weekday(day_name, include_today=False), type=round_type))
    return collections


SCRAPER = LibertyCreate(
    Meta(
        title="Hertsmere Borough Council",
        url="https://www.hertsmere.gov.uk",
        lads=("E07000098",),
        cases={
            "1 Abbots Place": {
                "postcode": "WD6 5QP",
                "house_number": "1",
                "street": "Abbots Place",
            },
            "Flat 1, 1 Shenley Road": {
                "postcode": "WD6 1AA",
                "house_number": "Flat 1",
                "street": "Shenley Road",
            },
        },
    ),
    LibertyCreateConfig(
        base_url="https://hertsmere-services.onmats.com",
        landing_path="/w/webpage/round-search",
        subpage_id="PAG0000830DCFEA1",
        address_field="PCF0019758",
        parse=_weekdays,
    ),
)
