"""Sunderland: search by postcode, select the matching address, then read bin dates."""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

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
    text_of,
)

_TITLE = "Sunderland City Council"
_URL = "https://www.sunderland.gov.uk/"
_PAGE_URL = "https://www.sunderland.gov.uk/bindays"
_FORM_PREFIX = "BINCOLLECTIONCHECKERNEWV3"
_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}
_BIN_TYPES = ("Household Green Bin", "Blue Recycling Bin", "Garden Waste")


def _get_hidden_fields(page: BeautifulSoup) -> dict[str, str]:
    """Extract hidden input fields whose names start with the form prefix."""
    fields: dict[str, str] = {}
    for tag in page.find_all("input", type="hidden"):
        name = tag.get("name", "")
        if isinstance(name, str) and name.startswith(_FORM_PREFIX):
            value = tag.get("value", "")
            fields[name] = value if isinstance(value, str) else str(value)
    return fields


def _get_submit_url(page: BeautifulSoup) -> str:
    """Extract the processsubmission URL from the form action."""
    form = page.find("form", id=f"{_FORM_PREFIX}_FORM")
    action = form.get("action") if isinstance(form, Tag) else None
    if isinstance(action, str) and action:
        return action
    raise UpstreamError("Could not find Sunderland's bin checker form action")


class Sunderland(Scraper):
    meta = Meta(
        title=_TITLE,
        url=_URL,
        lads=("E08000024",),
        cases={
            "Test_001": {"postcode": "SR4 7PU", "house_number": "191", "street": "Cleveland Road"},
            "Test_002": {"postcode": "SR3 2DW", "house_number": "43", "street": "Hill Street"},
            "Test_003": {"postcode": "SR4 8RJ", "house_number": "17", "street": "Sutherland Drive"},
        },
    )
    requires = frozenset({"postcode"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")

        # Step 1: GET the bin checker page to obtain session IDs and nonce.
        r = await http.get(_PAGE_URL, follow_redirects=True)
        page = soup(r.content)
        fields = _get_hidden_fields(page)
        submit_url = _get_submit_url(page)

        # Step 2: POST postcode to trigger address lookup.
        payload = dict(fields)
        payload.update(
            {
                f"{_FORM_PREFIX}_PAGENAME": "ADDRESSSEARCH",
                f"{_FORM_PREFIX}_PAGEINSTANCE": "0",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_SCCPOSTCODE": postcode,
                f"{_FORM_PREFIX}_FORMACTION_NEXT": f"{_FORM_PREFIX}_ADDRESSSEARCH_POSTCODETRIGGER",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_SCCLISTOFADDRESSES": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_POSTCODE": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_UPRN": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_RESIDUALBIN": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_TRADEBIN": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_RECYCLEBIN": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_GARDENBIN": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_NEXTBIN": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_PDFURL": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_LAT": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_LNG": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_ADDRESSTEXT": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_DATARETURNED": "",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_DATARETURNED2": "",
            }
        )

        r = await http.post(submit_url, data=payload, follow_redirects=True)
        page = soup(r.content)

        # Step 3: Extract address options; their values are used as the UPRN.
        fields = _get_hidden_fields(page)
        submit_url = _get_submit_url(page)
        select = page.find(
            "select", {"name": f"{_FORM_PREFIX}_ADDRESSSEARCH_SCCLISTOFADDRESSES"}
        )
        options = [
            option
            for option in (select.find_all("option") if isinstance(select, Tag) else [])
            if option.get("value")
        ]
        if not options:
            raise AddressNotFound(
                f"Sunderland returned no addresses for postcode {postcode!r}"
            )

        selected = match_address(
            address,
            options,
            text=text_of,
            uprn=lambda option: option.get("value"),
        )
        uprn_value = selected.get("value")
        if not isinstance(uprn_value, str):
            raise AddressNotFound(f"No matching Sunderland address for {address.label!r}")
        matched_address = text_of(selected)

        # Step 4: POST the selected address to retrieve collection dates.
        payload = dict(fields)
        payload.update(
            {
                f"{_FORM_PREFIX}_PAGENAME": "ADDRESSSEARCH",
                f"{_FORM_PREFIX}_PAGEINSTANCE": "1",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_SCCPOSTCODE": postcode,
                f"{_FORM_PREFIX}_FORMACTION_NEXT": f"{_FORM_PREFIX}_ADDRESSSEARCH_POSTCODETRIGGER",
                f"{_FORM_PREFIX}_ADDRESSSEARCH_SCCLISTOFADDRESSES": uprn_value,
                f"{_FORM_PREFIX}_ADDRESSSEARCH_POSTCODE": postcode,
                f"{_FORM_PREFIX}_ADDRESSSEARCH_UPRN": uprn_value,
                f"{_FORM_PREFIX}_ADDRESSSEARCH_ADDRESSTEXT": matched_address,
            }
        )

        r = await http.post(submit_url, data=payload, follow_redirects=True)
        page = soup(r.content)

        # Step 5: Parse collection dates from the results page.
        collections: list[Collection] = []
        for bin_type in _BIN_TYPES:
            title_el = page.find("p", string=re.compile(re.escape(bin_type), re.IGNORECASE))
            if not isinstance(title_el, Tag):
                continue

            container = title_el.parent
            date_el = container.find("p", class_=re.compile(r"myaccount-block__date")) if isinstance(container, Tag) else None
            if not isinstance(date_el, Tag):
                continue

            try:
                day = datetime.strptime(text_of(date_el), "%a %b %d %Y").date()
            except ValueError:
                continue
            collections.append(Collection(day, bin_type))

        if not collections:
            raise UpstreamError(
                "No collection dates could be parsed from Sunderland's bin-day portal"
            )
        return collections


SCRAPER = Sunderland()
