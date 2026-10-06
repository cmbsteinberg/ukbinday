"""Liverpool: fetches the bin-date table for a property using its UPRN."""

from __future__ import annotations

from datetime import date, timedelta

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    find_tag,
    parse_date,
    soup,
)

API_URL = (
    "https://liverpool.gov.uk/Bins/BinDatesTable"
    "?UPRN={uprn}&HideGreenBin=False&ShowTable=True"
)


class Liverpool(Scraper):
    meta = Meta(
        title="Liverpool City Council",
        url="https://www.liverpool.gov.uk",
        lads=("E08000012",),
        cases={
            "52 Swallowhurst Crescent Liverpool L11 2UZ": {"uprn": "38148233"},
            "1 Aston Street Liverpool L19 8LR": {"uprn": "38010019"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        today = date.today()
        r = await http.get(API_URL.format(uprn=address.need("uprn")))
        tables = soup(r.text).find_all("table")
        if not tables:
            raise UpstreamError("Liverpool's bin-date page has no table")

        collections = []
        for row in tables[0].find_all("tr")[1:]:
            bin_type = " ".join(find_tag(row, "th").get_text().split())
            for field in row.find_all("td"):
                collection_text = " ".join(field.get_text().split())
                if collection_text.startswith("Today"):
                    collection_date = today
                elif collection_text.startswith("Tomorrow"):
                    collection_date = today + timedelta(days=1)
                else:
                    collection_date = parse_date(collection_text, today=today)
                collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Liverpool()
