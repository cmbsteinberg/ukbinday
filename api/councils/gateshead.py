"""Gateshead: submit a UPRN to the bin checker and decode its returned collection table."""

from __future__ import annotations

import base64
import binascii
import json
import re

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    find_tag,
    parse_date,
    soup,
)

PAGE = "https://www.gateshead.gov.uk/article/3150/Bin-collection-day-checker"
_FORM_DATA_PATTERN = re.compile(
    r'var BINCOLLECTIONCHECKERFormData = "(.*?)";$', re.MULTILINE | re.DOTALL
)
_DAY_CHANGE_PATTERN = re.compile(r"(.*?)\s*-?\s*DAY CHANGE\s*$", re.IGNORECASE | re.DOTALL)


def _required_input_value(page: object, name: str) -> str:
    """Read a required form input value from the checker page."""
    if not hasattr(page, "find"):
        raise UpstreamError("Could not read Gateshead's bin checker form")
    node = page.find("input", attrs={"name": name})  # type: ignore[union-attr]
    value = node.get("value") if isinstance(node, Tag) else None
    if not isinstance(value, str):
        raise UpstreamError(f"Could not find {name}")
    return value


class Gateshead(Scraper):
    meta = Meta(
        title="Gateshead Council",
        url=PAGE,
        lads=("E08000037",),
        cases={
            "Test_001": {"uprn": "100000077407"},
            "Test_002": {"uprn": "100000058404"},
            "Test_003": {"uprn": "100000033887"},
        },
    )
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(PAGE, timeout=30)
        page = soup(r.text)

        form = page.find("form", attrs={"id": "BINCOLLECTIONCHECKER_FORM"})
        form_url = form.get("action") if isinstance(form, Tag) else None
        if not isinstance(form_url, str):
            raise UpstreamError("Could not find Gateshead's bin checker form or form action")

        form_data = {
            "BINCOLLECTIONCHECKER_PAGESESSIONID": _required_input_value(
                page, "BINCOLLECTIONCHECKER_PAGESESSIONID"
            ),
            "BINCOLLECTIONCHECKER_SESSIONID": _required_input_value(
                page, "BINCOLLECTIONCHECKER_SESSIONID"
            ),
            "BINCOLLECTIONCHECKER_NONCE": _required_input_value(
                page, "BINCOLLECTIONCHECKER_NONCE"
            ),
            "BINCOLLECTIONCHECKER_FORMACTION_NEXT": "BINCOLLECTIONCHECKER_ADDRESSSEARCH_NEXTBUTTON",
            "BINCOLLECTIONCHECKER_ADDRESSSEARCH_UPRN": address.need("uprn"),
            "BINCOLLECTIONCHECKER_ADDRESSSEARCH_ADDRESSTEXT": " ",
        }

        r = await http.post(form_url, data=form_data)
        page = soup(r.text)
        script = find_tag(page, "script", string=_FORM_DATA_PATTERN, what="Could not find BINCOLLECTIONCHECKERFormData in response")

        match = _FORM_DATA_PATTERN.search(script.text)
        if match is None:
            raise UpstreamError("Could not extract BINCOLLECTIONCHECKERFormData value")

        try:
            decoded_data = base64.b64decode(match.group(1))
            data = json.loads(decoded_data)
        except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
            raise UpstreamError(f"Could not decode Gateshead's bin checker response: {exc}") from exc

        if not isinstance(data, dict) or "HOUSEHOLDCOLLECTIONS_1" not in data:
            raise UpstreamError("HOUSEHOLDCOLLECTIONS_1 not found in response data")
        household = data["HOUSEHOLDCOLLECTIONS_1"]
        if not isinstance(household, dict) or "DISPLAYHOUSEHOLD" not in household:
            raise UpstreamError("DISPLAYHOUSEHOLD not found in response data")
        display_household = household["DISPLAYHOUSEHOLD"]
        if not isinstance(display_household, str):
            raise UpstreamError("Gateshead's collection table was not HTML")

        table = soup(display_household)
        collections = []
        month = None
        for row in table.find_all("tr"):
            month_th = row.find("th", attrs={"colspan": "3"})
            if month_th:
                month = month_th.text.split(" ")[0]
                continue
            if not month:
                continue

            cells = row.find_all("td")
            if len(cells) != 3:
                continue
            day = cells[0].text.strip()
            waste_types = cells[2].text.split(" and ")
            try:
                collection_date = parse_date(f"{day} {month.capitalize()}")
            except ValueError as exc:
                raise UpstreamError("Could not parse a date in Gateshead's collection table") from exc

            for waste_type in waste_types:
                day_change_match = _DAY_CHANGE_PATTERN.match(waste_type)
                if day_change_match:
                    waste_type = day_change_match.group(1)
                collections.append(Collection(collection_date, waste_type.strip()))

        return collections


SCRAPER = Gateshead()
