"""Harborough: submit a UPRN to FCC Environment and parse the returned collection days."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_URI1 = "https://harborough.fccenvironment.co.uk/"
_URI2 = "https://harborough.fccenvironment.co.uk/detail-address"


class Harborough(Scraper):
    meta = Meta(
        title="Harborough",
        url="https://www.harborough.gov.uk",
        lads=("E07000131",),
        cases={},
    )
    requires = frozenset({"uprn"})
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        await http.get(_URI1)
        response = await http.post(_URI2, data={"Uprn": uprn}, check=False)

        if response.status_code == 502:
            raise UpstreamError(
                "The FCC Environment service is currently unavailable (502 Bad Gateway)."
            )
        if response.status_code >= 400:
            raise UpstreamError(f"HTTP {response.status_code} from {response.url}")

        page = soup(response.content)
        bin_collection = page.find(
            "div", {"class": "blocks block-your-next-scheduled-bin-collection-days"}
        )
        if bin_collection is None:
            raise AddressNotFound(f"Could not find bin collection data for UPRN {uprn}")

        collections: list[Collection] = []
        for li in bin_collection.find_all("li"):
            date_span = li.find("span", {"class": "pull-right"})
            if date_span:
                date_text = date_span.get_text().strip()
                try:
                    day = datetime.strptime(date_text, "%d %B %Y").date()
                except ValueError:
                    continue
                bin_type = li.get_text().replace(date_text, "").strip()
            else:
                split = re.match(r"(.+)\s(\d{1,2} \w+ \d{4})$", li.get_text())
                if not split:
                    continue
                bin_type = split.group(1).strip()
                try:
                    day = datetime.strptime(split.group(2), "%d %B %Y").date()
                except ValueError:
                    continue

            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Harborough()
