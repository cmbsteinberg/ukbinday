"""Swansea: posts the UPRN and postcode to its ASP.NET recycling search page."""

from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_URL = "https://www1.swansea.gov.uk/recyclingsearch/"
_HEADERS = {"user-agent": "Mozilla/5.0"}


def _get_session_variable(page: BeautifulSoup, field_id: str) -> str | None:
    """Extract an ASP.NET hidden input value."""
    element = page.find("input", {"id": field_id})
    if element:
        value = element.get("value")
        return value if isinstance(value, str) else None
    raise ValueError(f"Unable to find element with id: {field_id}")


class Swansea(Scraper):
    meta = Meta(
        title="Swansea",
        url=_URL,
        lads=("W06000011",),
        cases={},
    )
    requires = frozenset({"uprn", "postcode"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(_URL)
        page = soup(response.text)

        data = {
            "__VIEWSTATE": _get_session_variable(page, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": _get_session_variable(page, "__VIEWSTATEGENERATOR"),
            "__VIEWSTATEENCRYPTED": "",
            "__EVENTVALIDATION": _get_session_variable(page, "__EVENTVALIDATION"),
            "txtRoadName": address.need("uprn"),
            "txtPostCode": address.need("postcode"),
            "btnSearch": "Search",
        }

        response = await http.post(_URL, data=data)
        page = soup(response.text)

        refuse_element = page.find("span", {"id": "lblNextRefuse"})
        recycling_element = page.find("span", {"id": "lblNextRecycling"})
        if refuse_element is None or recycling_element is None:
            raise UpstreamError("Swansea's recycling search response is missing collection dates")

        dates = (
            ("Pink Week", refuse_element.text.strip()),
            ("Green Week", recycling_element.text.strip()),
        )
        collections: list[Collection] = []
        for bin_type, date_str in dates:
            if not date_str:
                continue
            try:
                if "-" in date_str:
                    day = datetime.strptime(date_str, "%Y-%m-%d").date()
                elif "/" in date_str:
                    day = datetime.strptime(date_str, "%d/%m/%Y").date()
                else:
                    continue
            except ValueError:
                continue
            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Swansea()
