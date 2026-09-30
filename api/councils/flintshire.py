"""Flintshire: POST a UPRN to the bin-day service and parse its HTML collection rows."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_API_URL = "https://digital.flintshire.gov.uk/FCC_BinDay/Home/Details2/{uprn}"


class Flintshire(Scraper):
    meta = Meta(
        title="Flintshire",
        url="https://flintshire.gov.uk/",
        lads=("W06000005",),
        cases={
            "100100211557": {"uprn": "100100211557"},
            "200001744973": {"uprn": "200001744973"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        r = await http.post(_API_URL.format(uprn=uprn), check=False)
        if r.status_code == 500:
            raise InputError("web request failed: probably caused by an invalid UPRN")
        if r.status_code >= 400:
            raise UpstreamError(f"HTTP {r.status_code} from {r.url}")

        page = soup(r.text)
        collections = []

        for row in page.find_all("div", class_="col-md-12"):
            cols = [x.text.strip() for x in row.find_all("div")]
            if len(cols) == 0 or not re.match(r"\d{2}/\d{2}/\d{4}", cols[0]):
                continue

            day = datetime.strptime(cols[0], "%d/%m/%Y").date()
            for waste_type in cols[2].split("/"):
                collections.append(Collection(day, waste_type.strip()))

        return collections


SCRAPER = Flintshire()
