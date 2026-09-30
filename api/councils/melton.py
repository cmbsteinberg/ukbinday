"""Melton: sets the requested UPRN as the location and reads its collection dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup, text_of

_URL = "https://my.melton.gov.uk/set-location"
_HEADERS = {"user-agent": "Mozilla/5.0"}


class Melton(Scraper):
    meta = Meta(
        title="Melton Borough Council",
        url="https://www.melton.gov.uk/",
        lads=("E07000133",),
        cases={
            "Test_001": {"uprn": "100030544791"},
            "Test_002": {"uprn": "100030549260"},
            "Test_003": {"uprn": "100030537000"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _URL,
            params={
                "id": address.need("uprn"),
                "redirect": "collections",
                "rememberloc": "",
            },
        )
        page = soup(r.text)

        collections = []
        for item in page.find_all("li", {"class": ["dark-blue", "burgundy"]}):
            waste_type = text_of(item.find("h2"))
            waste_dates = text_of(item.find("strong")).split(", and then ")
            for waste_date in waste_dates:
                collections.append(
                    Collection(
                        date=datetime.strptime(waste_date, "%d/%m/%Y").date(),
                        type=waste_type,
                    )
                )
        return collections


SCRAPER = Melton()
