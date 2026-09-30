"""Preston: search its ASP.NET bin service, select a property, then parse collection dates."""

from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
    soup,
    text_of,
)

_SRV_URL = "https://selfservice.preston.gov.uk/service/Forms/FindMyNearest.aspx?Service=bins"

_HEADER_MAP = {
    "Food waste:": "Food Waste",
    "Commercial -  general waste:": "General Waste (Commercial)",
    "Commercial -  cardboard and paper:": "Cardboard (Commercial)",
    "Commercial - plastic cans and glass:": "Plastic (Commercial)",
    "Commercial -  food waste:": "Food Waste (Commercial)",
    "Black/grey bin (general waste):": "General Waste (Black/Grey bin)",
    "Yellow lidded recycling container (glass/cans/plastics):": "Glass/Cans/Plastics (Yellow bin)",
    "Red lidded recycling container (paper/card):": "Cardboard/Paper (Red bin)",
    "Brown bin (garden waste):": "Garden/Green Waste (Brown bin)",
}


def _extract_hidden_inputs(page: BeautifulSoup) -> dict[str, str]:
    """Extract all hidden input fields from a page."""
    params: dict[str, str] = {}
    for inp in page.find_all("input", {"type": "hidden"}):
        name = inp.get("name")
        if isinstance(name, str) and name:
            params[name] = str(inp.get("value", ""))
    return params


def _option_uprn(option: Tag) -> str | None:
    """Read a UPRN embedded in an option's value or label, when present."""
    candidate = f"{option.get('value', '')} {text_of(option)}"
    match = re.search(r"(?<!\d)\d{12}(?!\d)", candidate)
    return match.group(0) if match else None


def _date(date_string: str) -> date | None:
    try:
        return datetime.strptime(date_string, "%A %d/%m/%Y").date()
    except ValueError:
        return None


def _parse(container: Tag) -> list[Collection]:
    entries: list[Collection] = []
    for block in container.find_all("div", {"id": "container"}):
        header = block.select_one("ul > b")
        if header is None:
            continue

        header_text = text_of(header)
        bin_type = _HEADER_MAP.get(header_text) or header_text.rstrip(":")
        for item in block.select("ul > li"):
            date_span = item.select_one("span")
            if date_span is None:
                continue
            collection_date = _date(text_of(date_span))
            if collection_date is not None:
                entries.append(Collection(collection_date, bin_type))
    return entries


class Preston(Scraper):
    meta = Meta(
        title="Preston City Council",
        url="https://preston.gov.uk",
        lads=("E07000123",),
        cases={
            "Test_001": {"street": "town hall, lancaster road"},
            "Test_002": {"street": "PR1 2RL", "uprn": "10002220003"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        search_text = address.street or address.postcode or address.first_line
        if not search_text:
            raise InputError("Preston needs a street, postcode, or address")

        uprn = address.uprn or ""

        r0 = await http.get(_SRV_URL)
        page0 = soup(r0.text)

        params1 = _extract_hidden_inputs(page0)
        params1["__EVENTTARGET"] = "ctl00$MainContent$btnSearch"
        params1["__EVENTARGUMENT"] = ""
        params1["ctl00$MainContent$hdnService"] = "bins"
        params1["ctl00$MainContent$txtAddress"] = search_text
        params1["ctl00$MainContent$hdnUPRN"] = uprn

        r1 = await http.post(_SRV_URL, data=params1)
        page1 = soup(r1.text)

        result_container = page1.select_one("span#MainContent_lblMoreCollectionDates")
        if result_container is not None and result_container.find_all("div", {"id": "container"}):
            return _parse(result_container)

        select = page1.find("select", {"name": "ctl00$MainContent$ddlSearchResults"})
        if not isinstance(select, Tag):
            raise AddressNotFound(f"Preston found no address for {search_text!r}")

        options = [
            option
            for option in select.find_all("option")
            if isinstance(option, Tag)
            and (
                str(option.get("value", "")).startswith("170|")
                or str(option.get("value", "")).count("|") >= 4
            )
        ]

        if not options:
            suggestions = [
                text_of(option)
                for option in select.find_all("option")
                if str(option.get("value", "")) not in ("Make a selection from the list", "")
            ]
            raise AddressNotFound(
                f"Preston found no address for {search_text!r}",
                suggestions,
            )

        try:
            selected_option = match_address(
                address,
                options,
                text=text_of,
                uprn=_option_uprn,
            )
        except AddressNotFound:
            # The council's old flow selected the first result when no match was found.
            selected_option = options[0]

        selected_value = str(selected_option.get("value", ""))

        params2 = _extract_hidden_inputs(page1)
        params2["__EVENTTARGET"] = "ctl00$MainContent$ddlSearchResults"
        params2["__EVENTARGUMENT"] = ""
        params2["ctl00$MainContent$hdnService"] = "bins"
        params2["ctl00$MainContent$txtAddress"] = search_text
        params2["ctl00$MainContent$ddlSearchResults"] = selected_value

        r2 = await http.post(_SRV_URL, data=params2)
        page2 = soup(r2.text)

        result_container = page2.select_one("span#MainContent_lblMoreCollectionDates")
        if result_container is None or not result_container.find_all("div", {"id": "container"}):
            raise AddressNotFound(f"Preston has no bin collections for {search_text!r}")

        return _parse(result_container)


SCRAPER = Preston()
