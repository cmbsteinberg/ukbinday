"""Worcester: POST the UPRN to its self-service lookup and parse the returned table."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup, text_of

_LOOKUP_URL = "https://selfserve.worcester.gov.uk/wccroundlookup/HandleSearchScreen"
_REQUEST_HEADERS = {
    "referer": _LOOKUP_URL,
    "content-type": "application/x-www-form-urlencoded",
}


class Worcester(Scraper):
    meta = Meta(
        title="Worcester",
        url="https://www.Worcester.gov.uk",
        lads=("E07000237",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.post(
            _LOOKUP_URL,
            data={"alAddrsel": address.need("uprn")},
            headers=_REQUEST_HEADERS,
        )

        collections: list[Collection] = []
        for row in soup(response.content).select("table.table tbody tr"):
            bin_type = text_of(row.select_one("td:nth-of-type(2)"))
            collection_date = text_of(row.select_one("td:nth-of-type(3) strong"))

            if collection_date == "Not applicable":
                continue

            try:
                day = datetime.strptime(collection_date, "%A %d/%m/%Y").date()
            except ValueError:
                continue
            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Worcester()
