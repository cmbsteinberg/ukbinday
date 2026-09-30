"""North West Leicestershire: fetches collection dates from the UPRN-specific location page."""

from __future__ import annotations

from datetime import date, timedelta

from bs4 import Tag
from dateutil import parser as dateutil_parser

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_API_URL = "https://my.nwleics.gov.uk/location?put=nwl{uprn}&rememberme=0&redirect=%2F"


class NorthWestLeicestershire(Scraper):
    meta = Meta(
        title="North West Leicestershire District Council",
        url="https://nwleics.gov.uk/",
        lads=("E07000134",),
        cases={
            "Dunmore": {"uprn": "10002359002"},
            "Station Road": {"uprn": "100030573554"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_API_URL.format(uprn=address.need("uprn")))
        page = soup(r.text)

        refuse = page.find("ul", class_="refuse")
        if not isinstance(refuse, Tag):
            raise UpstreamError("North West Leicestershire page has no refuse collections")

        entries: list[Collection] = []
        for li in refuse.find_all("li"):
            strong_tag = li.find("strong")
            a_tag = li.find("a")
            if not isinstance(strong_tag, Tag) or not isinstance(a_tag, Tag):
                continue

            date_str = strong_tag.contents[0].strip()
            date_str_lower = date_str.lower()
            if date_str_lower == "today":
                collection_date = date.today()
            elif date_str_lower == "tomorrow":
                collection_date = date.today() + timedelta(days=1)
            else:
                collection_date = dateutil_parser.parse(date_str).date()

            bin_type = str(a_tag.contents[0])
            entries.append(Collection(collection_date, bin_type))

        return entries


SCRAPER = NorthWestLeicestershire()
