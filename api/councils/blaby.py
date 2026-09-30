"""Blaby: set the location by UPRN, then read collection dates from the collections page."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_SET_LOCATION_URL = "https://my.blaby.gov.uk/set-location.php"
_COLLECTIONS_URL = "https://my.blaby.gov.uk/collections"
_DATE_REGEX = re.compile(r"\d{2}/\d{2}/\d{4}")
_BIN_TYPES = frozenset({"Refuse", "Recycling", "Garden", "Food waste"})


class Blaby(Scraper):
    meta = Meta(
        title="Blaby District Council",
        url=_COLLECTIONS_URL,
        lads=("E07000129",),
        cases={
            "Test_001": {"uprn": "100030407500"},
            "Test_002": {"uprn": "100030395499"},
            "Test_003": {"uprn": "10001238216"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        await http.get(
            _SET_LOCATION_URL,
            params={"ref": uprn, "redirect": "collections"},
            timeout=30,
        )
        r = await http.get(_COLLECTIONS_URL, timeout=30)

        page = soup(r.text)
        entries: list[Collection] = []

        for heading in page.find_all("h2"):
            bin_type = heading.get_text(strip=True)
            if bin_type not in _BIN_TYPES:
                continue

            content = []
            for sibling in heading.next_siblings:
                if getattr(sibling, "name", None) == "h2":
                    break
                if hasattr(sibling, "get_text"):
                    content.append(sibling.get_text(" ", strip=True))

            text = " ".join(content)
            for day in _DATE_REGEX.findall(text):
                entries.append(
                    Collection(datetime.strptime(day, "%d/%m/%Y").date(), bin_type)
                )

        return entries


SCRAPER = Blaby()
