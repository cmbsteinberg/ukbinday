"""South Derbyshire: looks up the next bin collections by UPRN in the council's map API."""

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
)

_API_URL = (
    "https://maps.southderbyshire.gov.uk/iShareLIVE.web/getdata.aspx"
    "?RequestType=LocalInfo&ms=mapsources/MyHouse&format=JSON"
    "&group=Recycling%20Bins%20and%20Waste|Next%20Bin%20Collections&uid="
)


def _extract_date(text: str) -> date:
    match = re.search(r"(\d{2} \w+ \d{4})", text)
    if match is None:
        raise ValueError("No collection date found")
    return datetime.strptime(match.group(1), "%d %B %Y").date()


class SouthDerbyshire(Scraper):
    meta = Meta(
        title="South Derbyshire District Council",
        url="https://www.southderbyshire.gov.uk/",
        lads=("E07000039",),
        cases={
            "test case 1": {"uprn": "100030233745"},
            "test case 2": {"uprn": "10090304958"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{_API_URL}{address.need('uprn')}")
        page = soup(r.json()["Results"]["Next_Bin_Collections"]["_"])
        collections = page.find_all("div", recursive=False)

        if not collections:
            raise AddressNotFound(f"South Derbyshire has no bin schedule for UPRN {address.uprn}")

        entries = []
        for collection in collections:
            image = collection.find("img")
            if image is None:
                continue
            try:
                day = _extract_date(collection.get_text())
            except ValueError:
                continue

            for bin_type in re.findall(r"Green|Brown|Black|Podback", image.get("alt", "")):
                entries.append(
                    Collection(
                        day,
                        bin_type if bin_type == "Podback" else bin_type + " bin",
                    )
                )

        return entries


SCRAPER = SouthDerbyshire()
