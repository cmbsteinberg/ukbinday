"""Windsor and Maidenhead: looks up bin collections using the property's UPRN."""

from __future__ import annotations

from dateutil.parser import parse

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    soup,
)

API_URL = "https://forms.rbwm.gov.uk/bincollections"


class WindsorAndMaidenhead(Scraper):
    meta = Meta(
        title="Windsor and Maidenhead",
        url="https://my.rbwm.gov.uk/",
        lads=("E06000040",),
        cases={
            "Windsor 1": {"postcode": "SL4 4EN", "uprn": "100080381393"},
            "Windsor 2": {"uprn": "100080384194"},
            "Maidenhead 1": {"uprn": "100080359672"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        response = await http.get(API_URL, params={"uprn": uprn})

        table = soup(response.text).find("table")
        if table is None:
            raise AddressNotFound(f"Windsor and Maidenhead has no collections for UPRN {uprn}")

        collections = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) != 2:
                continue

            bin_type = cells[0].text.split("Collection Service")[0].strip()
            collection_date = parse(cells[1].text.strip()).date()
            collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = WindsorAndMaidenhead()
