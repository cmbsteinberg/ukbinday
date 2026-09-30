"""Herefordshire: searches a postcode for a property, then fetches its bin-day page by UPRN."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bs4 import Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
)

_ADDRESS_SEARCH_URL = "https://trsewmllv7.execute-api.eu-west-2.amazonaws.com/dev/address"
_COLLECTION_URL = "https://www.herefordshire.gov.uk/rubbish-recycling/check-bin-collection-day"
_HEADERS = {"user-agent": "Mozilla/5.0"}


def _first_li_after_heading(container: Tag, heading_keyword: str) -> list[str]:
    results: list[str] = []
    for h3 in container.find_all("h3"):
        if heading_keyword.lower() not in h3.get_text(strip=True).lower():
            continue
        ul = h3.find_next_sibling("ul")
        if not isinstance(ul, Tag):
            continue
        for li in ul.find_all("li"):
            text = li.get_text(strip=True)
            cut = text.find("(")
            results.append(text[:cut].strip() if cut != -1 else text.strip())
    return results


class Herefordshire(Scraper):
    meta = Meta(
        title="Herefordshire City Council",
        url="https://www.herefordshire.gov.uk/rubbish-recycling/check-bin-collection-day",
        lads=("E06000019",),
        cases={
            "houseNumber": {"postcode": "HR4 9JS", "house_number": "52"},
            "uprn": {"postcode": "HR4 9JS", "house_number": "200002607460"},
        },
    )
    requires = frozenset({"postcode", "house_number"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(
            _ADDRESS_SEARCH_URL,
            params={"postcode": address.need("postcode"), "type": "standard"},
        )
        payload: Any = response.json()
        if payload.get("error") or "results" not in payload or not payload["results"]:
            raise AddressNotFound(f"Herefordshire has no addresses for postcode {address.postcode}")

        candidates = [result["LPI"] for result in payload["results"]]
        selected = match_address(
            address,
            candidates,
            text=lambda lpi: str(lpi.get("ADDRESS") or ""),
            uprn=lambda lpi: lpi.get("UPRN"),
        )

        response = await http.get(
            _COLLECTION_URL,
            params={"blpu_uprn": selected["UPRN"]},
        )
        page = soup(response.text)
        container = page.find(id="binCollectionDetails")
        if not isinstance(container, Tag):
            container = page.find(id="wasteCollectionDates")
        if not isinstance(container, Tag):
            raise UpstreamError("Could not find Herefordshire's bin collection section")

        sections = (
            ("General rubbish", _first_li_after_heading(container, "general rubbish")),
            ("Recycling", _first_li_after_heading(container, "recycling")),
            ("Garden", _first_li_after_heading(container, "garden waste")),
        )

        collections: list[Collection] = []
        for waste_type, date_strings in sections:
            for date_string in date_strings:
                try:
                    day = datetime.strptime(date_string, "%A %d %B %Y").date()
                except ValueError:
                    continue
                collections.append(Collection(day, waste_type))

        if not collections:
            raise UpstreamError("Herefordshire returned no collection dates for this address")
        return collections


SCRAPER = Herefordshire()
