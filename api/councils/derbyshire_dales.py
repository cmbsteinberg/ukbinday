"""Derbyshire Dales: a Firmstep form that takes the address key ("U" + UPRN) directly.

The results page lists `date / service` rows; the council names only the
recycling round, so garden waste is added on the same day (as the old scraper did).
"""

from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup

from api.councils._base import Collection, Meta
from api.councils._platforms.firmstep import (
    FirmstepAddressForm,
    FirmstepAddressFormConfig,
)

_HOST = "https://selfserve.derbyshiredales.gov.uk"


def _parse(page: BeautifulSoup) -> list[Collection]:
    collections: list[Collection] = []
    for row in page.select("div.ss_confPanel div.row[style*='padding-left']"):
        date_col = row.find("div", class_="col-sm-5")
        type_col = row.find("div", class_="col-sm-6")
        if not date_col or not type_col:
            continue
        raw_date = date_col.get_text(separator=" ", strip=True)
        lower = type_col.get_text(strip=True).lower()
        try:
            day = datetime.strptime(raw_date, "%A %d %B, %Y").date()
        except ValueError:
            continue

        if "domestic" in lower:
            collections.append(Collection(day, "Domestic Waste"))
        elif "recycling" in lower:
            collections.append(Collection(day, "Recycling Waste"))
            collections.append(Collection(day, "Garden Waste"))
        elif "food" in lower:
            collections.append(Collection(day, "Food Waste"))
        # Anything else (recycling sacks...) duplicates another row and is skipped.
    return collections


SCRAPER = FirmstepAddressForm(
    Meta(
        title="Derbyshire Dales District Council",
        url="https://www.derbyshiredales.gov.uk/",
        lads=("E07000035",),
        cases={
            "Matlock": {"postcode": "DE4 3GS"},
            "Bakewell": {"uprn": "10070089522"},
            "Wirksworth": {"uprn": "10070097828"},
        },
    ),
    FirmstepAddressFormConfig(
        form_url=f"{_HOST}/renderform?k=9644C066D2168A4C21BCDA351DA2642526359DFF&t=103",
        render_url=f"{_HOST}/RenderForm",
        lookup_url=f"{_HOST}/core/addresslookup",
        address_field="FF2924",
        field_suffixes={"lbltxt": "Collection Address", "-text": "False"},
        search_nlpg="False",
        parse=_parse,
    ),
)
