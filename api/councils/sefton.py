"""Sefton: search by postcode and street, select the matching address, then read its bin tables."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
    text_of,
)

_PAGE = "https://www.sefton.gov.uk/bins-and-recycling/bins-and-recycling/when-is-my-bin-collection-day/"


class Sefton(Scraper):
    meta = Meta(
        title="Sefton Council",
        url="https://www.sefton.gov.uk/",
        lads=("E08000014",),
        cases={
            "Issue2369": {"house_number": "1", "street": "Ken Mews", "postcode": "L20 6GF"},
            "Housename": {
                "house_number": "Gladstone House",
                "street": "Rosemary Lane",
                "postcode": "L37 3JB",
            },
            "Issue2496": {"house_number": "22", "street": "Elton Avenue", "postcode": "L23 8UW"},
        },
    )
    requires = frozenset({"postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if not address.first_line:
            raise InputError("Sefton needs a house name or number")

        r = await http.get(_PAGE, timeout=60)
        page = soup(r.content)
        hidden = page.find_all("input", {"type": "hidden"}, limit=2)
        payload = {item["name"]: item["value"] for item in hidden}
        payload["Postcode"] = address.need("postcode")
        payload["Streetname"] = address.street or ""

        r = await http.post(_PAGE, data=payload, timeout=60)
        page = soup(r.content)
        hidden = page.find_all("input", {"type": "hidden"})
        payload = {item["name"]: item["value"] for item in hidden}
        payload["action"] = "Select"

        options = page.select("select option")
        option = match_address(address, options, text=text_of)
        payload["selectedValue"] = option["value"]

        r = await http.post(_PAGE, data=payload, timeout=60)
        page = soup(r.content)
        tables = page.find_all("table")
        if not tables:
            raise UpstreamError(
                "No entries could be parsed; check that the Sefton website is working"
            )

        collections = []
        for table in tables:
            bin_type = table.td.text.split()[0]
            collection_date = datetime.strptime(
                table.td.findNext("td").findNext("td").text, "%d/%m/%Y"
            ).date()
            collections.append(Collection(collection_date, bin_type))
        return collections


SCRAPER = Sefton()
