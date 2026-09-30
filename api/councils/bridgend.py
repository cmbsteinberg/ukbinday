"""Bridgend: looks up a property's waste schedule by UPRN on the council portal."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

BASE = "https://bridgendportal.azurewebsites.net"
HEADERS = {"user-agent": "Mozilla/5.0"}


class Bridgend(Scraper):
    meta = Meta(
        title="Bridgend County Borough Council",
        url="https://www.bridgend.gov.uk/",
        lads=("W06000013",),
        cases={
            "test_001": {"uprn": "100100479873"},
            "test_002": {"uprn": "10032996088"},
            "test_003": {"uprn": "10090813443"},
        },
    )
    requires = frozenset({"uprn"})
    headers = HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(f"{BASE}/property/{address.need('uprn')}")
        page = soup(r.content)

        tds = page.find_all("td", {"class": ["service-name", "next-service"]})
        waste_types = tds[0::2]
        waste_dates = tds[1::2]

        collections = []
        for i in range(len(waste_types)):
            waste_type = waste_types[i].text.split(" ")[0].replace("\n", "").strip()
            waste_date = (
                waste_dates[i]
                .text.split(" ")[1]
                .replace("\t", "")
                .replace("Service\n", "")
                .strip()
            )
            collections.append(
                Collection(
                    date=datetime.strptime(waste_date, "%d/%m/%Y").date(),
                    type=waste_type,
                )
            )

        return collections


SCRAPER = Bridgend()
