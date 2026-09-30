"""Newark & Sherwood: looks up a UPRN in the bin calendar, then optionally checks the additional calendar."""

from __future__ import annotations

import calendar
import re
from datetime import date

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
    text_of,
)

_URL = "http://app.newark-sherwooddc.gov.uk/bincollection/calendar"
_BIN_NAMES = {
    "recycle": "Recycling",
    "refuse": "General",
    "garden": "Garden",
    "glass": "Glass",
}


class NewarkAndSherwood(Scraper):
    meta = Meta(
        title="Newark & Sherwood District Council",
        url="https://www.newark-sherwooddc.gov.uk/",
        lads=("E07000175",),
        cases={
            "Edwinstowe": {"uprn": "010091747078"},
            "Ollerton": {"uprn": "100031463343"},
            "Clipstone": {"uprn": "010091745473"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        collections = await _get_data(http, {"pid": uprn})
        try:
            collections += await _get_data(http, {"pid": uprn, "nc": "1"})
        except (UpstreamError, AttributeError, IndexError, KeyError, TypeError, ValueError):
            pass
        return collections


async def _get_data(http: Http, params: dict[str, str]) -> list[Collection]:
    response = await http.get(_URL, params=params, check=False)
    page = soup(response.content)
    collections: list[Collection] = []

    # Collections are arranged by month, with each month as an individual table.
    for month in page.find_all("table"):
        month_heading = text_of(month.find("th"))
        month_match = re.search(r"(\w*)\s*(\d{4})", month_heading)
        if month_match is None:
            continue

        month_name, year = month_match.groups()
        try:
            month_number = list(calendar.month_name).index(month_name)
        except ValueError:
            continue

        for row in month.find_all("tr", class_=re.compile("bin_")):
            classes = row.get("class", [])
            if not classes:
                continue
            type_match = re.search(r"bin_(\w*)", classes[0])
            day_match = re.search(r",\s*\w*\s*(\d{1,2})\w{2}", text_of(row.find("td")))
            if type_match is None or day_match is None:
                continue

            bin_type = type_match.group(1)
            try:
                collection_date = date(int(year), month_number, int(day_match.group(1)))
            except ValueError:
                continue

            collections.append(Collection(collection_date, _BIN_NAMES.get(bin_type, bin_type)))

    return collections


SCRAPER = NewarkAndSherwood()
