"""Swindon: posts the selected UPRN to its collection-days page and parses the results."""

from __future__ import annotations

from dateutil import parser

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_URL = "https://www.swindon.gov.uk/info/20122/rubbish_and_recycling_collection_days"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}


class Swindon(Scraper):
    meta = Meta(
        title="Swindon Borough Council",
        url="https://www.swindon.gov.uk",
        lads=("E06000030",),
        cases={
            "1 Nyland Road": {"uprn": "100121147490"},
            "74 Standen Way": {"uprn": "200002922415"},
            "1 Eastbury Way": {"uprn": "10010424600"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(
            _URL,
            params={"uprnSubmit": "Yes", "addressList": address.need("uprn")},
            check=False,
        )
        if r.status_code == 403 or "403 Client Error" in r.text:
            raise UpstreamError("Rate limiting or IP ban may be in effect")
        if r.status_code >= 400:
            raise UpstreamError(f"HTTP {r.status_code} from {r.url}")

        collections = []
        for results in soup(r.text).find_all("div", class_="bin-collection-content"):
            recyclingdate = results.find("span", class_="nextCollectionDate")
            if recyclingdate is not None:
                recyclingtype = results.find("div", class_="content-left").find("h3")
                collections.append(
                    Collection(
                        date=parser.parse(recyclingdate.text, dayfirst=True).date(),
                        type=recyclingtype.text,
                    )
                )
        return collections


SCRAPER = Swindon()
