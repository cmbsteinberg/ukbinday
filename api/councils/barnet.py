"""Barnet: looks up a property's bin collections by its zero-padded UPRN."""

from __future__ import annotations

from dateutil import parser

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_API_URL = "https://myforms.barnet.gov.uk/homepage/11/find-your-bin-collection-day"
_HEADERS = {"user-agent": "Mozilla/5.0"}


class Barnet(Scraper):
    meta = Meta(
        title="London Borough of Barnet",
        url="https://www.barnet.gov.uk/",
        lads=("E09000003",),
        cases={
            "Test_001": {"uprn": "200062903"},
            "Test_002": {"uprn": "200072958"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(
            _API_URL,
            params={"address": address.need("uprn").zfill(12)},
            timeout=10,
        )

        page = soup(r.text)
        collections = []
        bins = page.find_all("h4", class_="bin-collection__heading")
        dates = page.find_all("p", class_="bin-collection__date")
        for date_tag, bin_tag in zip(dates, bins, strict=True):
            day = parser.parse(date_tag.text).date()
            bin_name = bin_tag.text.strip()
            collections.append(Collection(day, bin_name))

        return collections


SCRAPER = Barnet()
