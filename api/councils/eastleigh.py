"""Eastleigh: fetches bin collections from its UPRN-keyed collection page."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Blocker,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    soup,
)

_API_URL = (
    "https://eastleigh.gov.uk/waste-bins-and-recycling/collection-dates/"
    "your-waste-bin-and-recycling-collections"
)


class Eastleigh(Scraper):
    meta = Meta(
        title="Eastleigh Borough Council",
        url="https://eastleigh.gov.uk",
        lads=("E07000086",),
        cases={
            "100060319000": {"uprn": "100060319000"},
            "100060300958": {"uprn": "100060300958"},
        },
    )
    requires = frozenset({"uprn"})
    blocker = Blocker.BOT_PROTECTION  # its site blocks Vercel's IPs (scripts/vercel_probe.py)
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL, params={"uprn": address.need("uprn")})
        page = soup(r.text)

        collections = []
        for dl in page.find_all("dl"):
            for dt in dl.find_all("dt"):
                dd = dt.find_next_sibling("dd")
                if not dd:
                    continue

                try:
                    day = datetime.strptime(dd.text.strip(), "%a, %d %b %Y").date()
                except ValueError:
                    continue

                collections.append(Collection(day, dt.text))
        return collections


SCRAPER = Eastleigh()
