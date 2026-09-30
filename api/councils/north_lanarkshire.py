"""North Lanarkshire: fetches collection dates from a page keyed by UPRN and USRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    soup,
    text_of,
)

_BASE = "https://www.northlanarkshire.gov.uk/bin-collection-dates"


class NorthLanarkshire(Scraper):
    meta = Meta(
        title="North Lanarkshire Council",
        url="https://northlanarkshire.gov.uk",
        lads=("S12000050",),
        cases={
            "Test_001": {"uprn": "118026605", "usrn": "48406574"},
            "Test_002": {"uprn": "118177268", "usrn": "48410258"},
            "Test_003": {"uprn": "000118035256", "usrn": "48409125"},
        },
    )
    requires = frozenset({"uprn", "usrn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        usrn = address.need("usrn")
        r = await http.get(f"{_BASE}/{uprn}/{usrn}")

        page = soup(r.text)
        containers = page.find_all("div", {"class": "waste-type-container"})

        collections = []
        for container in containers:
            waste_type = text_of(container.find("h3"))
            for day in container.find_all("p"):
                collections.append(
                    Collection(
                        date=datetime.strptime(day.get_text(), "%d %B %Y").date(),
                        type=waste_type,
                    )
                )

        return collections


SCRAPER = NorthLanarkshire()
