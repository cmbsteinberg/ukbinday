"""South Kesteven: a Firmstep form that takes the address key ("U" + UPRN) directly.

The results page is a table of `date / service` rows.
"""

from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup

from api.councils._base import Collection, Meta
from api.councils._platforms.firmstep import (
    FirmstepAddressForm,
    FirmstepAddressFormConfig,
)

_HOST = "https://selfservice.southkesteven.gov.uk"


def _parse(page: BeautifulSoup) -> list[Collection]:
    collections: list[Collection] = []
    for row in page.select("table.Alloy-table tr"):
        cols = row.find_all("td", class_="Alloy-table-col")
        if len(cols) < 2:
            continue
        try:
            day = datetime.strptime(cols[0].get_text(strip=True), "%A %d %B, %Y").date()
        except ValueError:
            continue
        collections.append(Collection(day, cols[1].get_text(strip=True)))
    return collections


SCRAPER = FirmstepAddressForm(
    Meta(
        title="South Kesteven District Council",
        url="https://southkesteven.gov.uk",
        lads=("E07000141",),
        cases={
            "Grantham": {"postcode": "NG31 8XG"},
            "Long Bennington": {"postcode": "NG23 5EQ"},
            "Grantham direct": {"uprn": "10007272306"},
        },
    ),
    FirmstepAddressFormConfig(
        form_url=f"{_HOST}/renderform?k=2074C945A63DDC0D18F1EB74DA230AC3122958B1&t=213",
        render_url=f"{_HOST}/RenderForm",
        lookup_url=f"{_HOST}/core/addresslookup",
        address_field="FF5265",
        field_suffixes={
            "lbltxt": "Collection Address",
            "searchnlpg": "False",
            "manualaddressentry": "False",
            "classification": "",
        },
        parse=_parse,
    ),
)
