"""Calderdale: POST the postcode and padded UPRN to the collection-day finder."""

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
    Transport,
    UpstreamError,
    soup,
)

_URL = "https://www.calderdale.gov.uk"
_API_URL = "https://www.calderdale.gov.uk/environment/waste/household-collections/collectiondayfinder.jsp"


class Calderdale(Scraper):
    meta = Meta(
        title="Calderdale Council",
        url=_URL,
        lads=("E08000033",),
        cases={
            "Test_1": {"postcode": "OL14 7BX", "uprn": "10010152783"},
            "Test_2": {"postcode": "HX1 3UZ", "uprn": "10006741170"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        uprn = address.need("uprn").zfill(12)
        response = await http.post(
            _API_URL,
            data={
                "postcode": postcode,
                "uprn": uprn,
                "gdprTerms": "Yes",
                "privacynoticeid": "323",
                "find": "Show me my collection days",
            },
        )

        page = soup(response.text)
        collection_table = page.find("table", {"id": "collection"})
        if not collection_table:
            address_check = page.find(
                "p",
                string=lambda text: (
                    text and "Currently showing collection days for:" in text
                ),
            )
            if not address_check:
                raise AddressNotFound(
                    "Could not find collection information for the provided UPRN "
                    "and postcode combination. Please verify both values are correct."
                )
            raise UpstreamError("Could not find collection schedule table in response")

        tbody = collection_table.find("tbody")
        rows = tbody.find_all("tr") if tbody else []
        collections: list[Collection] = []

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            waste_type_strong = cells[0].find("strong")
            if not waste_type_strong:
                continue
            waste_type = waste_type_strong.text.strip()

            collection_info_cell = cells[2]
            next_collection_p = None
            for paragraph in collection_info_cell.find_all("p"):
                if "will be your next collection" in paragraph.get_text():
                    next_collection_p = paragraph
                    break

            if not next_collection_p:
                continue

            date_match = re.search(
                r"(\w+\s+\d{1,2}\s+\w+\s+\d{4})", next_collection_p.get_text()
            )
            if not date_match:
                continue

            date_parts = date_match.group(1).split()
            if len(date_parts) < 4:
                continue

            date_str_clean = f"{date_parts[1]} {date_parts[2]} {date_parts[3]}"
            try:
                collection_date = datetime.strptime(date_str_clean, "%d %B %Y").date()
            except ValueError:
                continue

            collections.append(Collection(collection_date, waste_type))

        if not collections:
            raise AddressNotFound(f"No collection dates found for UPRN {uprn}")

        return collections


SCRAPER = Calderdale()
