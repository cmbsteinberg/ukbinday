"""Cheltenham: submit the checker’s property ID and parse its returned bin-schedule rows."""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_BASE_URL = "https://cheltenham-host01.oncreate.app"
_WEBPAGE_TOKEN = "3e546dda8816902a52a5e3f68096b16d45e279f1f634e9433b899675b5349448"
_SUBPAGE_ID = "PAG0000686GBCNH1"
_CELL_ID = "PCL0005127GBCNH1"
_FRAGMENT_ID = "PCF0019732GBCNH1"
_WIDGET_GROUP_ID = "PWG0002596GBCNH1"
_SUBMIT_FRAGMENT_ID = "PCF0016614GBCNH1"

_SCHEDULE_OBJECT_ID = "OBJ0000370GBCNH1"
_FRAGMENT_BIN_TYPE = "PCF0019703GBCNH1"
_FRAGMENT_NEXT_DATE = "PCF0019810GBCNH1"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


def _parse_schedule(html: str, property_id: str) -> list[Collection]:
    page = soup(html)
    rows = page.find_all("tr", attrs={"data-base_object_id": _SCHEDULE_OBJECT_ID})

    entries: list[Collection] = []
    for row in rows:
        bin_type_div = row.find("div", attrs={"data-fragment_id": _FRAGMENT_BIN_TYPE})
        next_date_div = row.find("div", attrs={"data-fragment_id": _FRAGMENT_NEXT_DATE})
        if not isinstance(bin_type_div, Tag) or not isinstance(next_date_div, Tag):
            continue

        bin_type_value = bin_type_div.get("data-current_value", "")
        next_date_value = next_date_div.get("data-current_value", "")
        bin_type = bin_type_value.strip() if isinstance(bin_type_value, str) else ""
        next_date_str = next_date_value.strip() if isinstance(next_date_value, str) else ""
        if not bin_type or not next_date_str or next_date_str == "N/A":
            continue

        try:
            next_date = datetime.strptime(next_date_str, "%d/%m/%Y").date()
        except ValueError:
            continue

        entries.append(Collection(date=next_date, type=bin_type))

    if not entries:
        raise UpstreamError(
            f"No collection data found — please check property_id {property_id!r}"
        )

    return entries


class Cheltenham(Scraper):
    meta = Meta(
        title="Cheltenham Borough Council",
        url="https://www.cheltenham.gov.uk",
        lads=("E07000078",),
        cases={
            "282 Hatherley Road GL51 6HR": {"property_id": "56299"},
            "Second property": {"property_id": "55297"},
        },
    )
    needs_browser = "Cheltenham's bin lookup now needs an interactive page flow."
    requires = frozenset({"property_id"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        property_id = address.need("property_id")
        page_url = (
            f"{_BASE_URL}/w/webpage/collection-lookup"
            f"?webpage_subpage_id={_SUBPAGE_ID}&webpage_token={_WEBPAGE_TOKEN}"
        )

        r1 = await http.get(page_url)
        data1 = r1.json().get("data", "")

        form_check_match = re.search(r'name="form_check" value="([a-f0-9]+)"', data1)
        if not form_check_match:
            raise UpstreamError("Could not extract CSRF token from Cheltenham's form response")
        form_check = form_check_match.group(1)

        collection_key_match = re.search(r'data-unique_key="(C_[a-f0-9]+)"', data1)
        if not collection_key_match:
            raise UpstreamError("Could not extract collection key from Cheltenham's form response")
        collection_key = collection_key_match.group(1)

        r2 = await http.post(
            page_url,
            data={
                "form_check": form_check,
                "submitted_page_storage_key": "/w/webpage/collection-lookup",
                "submitted_page_id": _SUBPAGE_ID,
                "submitted_widget_group_id": _WIDGET_GROUP_ID,
                "submitted_widget_group_type": "search",
                f"payload[{_SUBPAGE_ID}][{_WIDGET_GROUP_ID}][{_CELL_ID}][search][{collection_key}][{_FRAGMENT_ID}]": property_id,
                f"payload[{_SUBPAGE_ID}][{_WIDGET_GROUP_ID}][{_CELL_ID}][search][{collection_key}][{_SUBMIT_FRAGMENT_ID}]": "Next",
            },
        )
        data2 = r2.json().get("data", "")

        return _parse_schedule(data2, property_id)


SCRAPER = Cheltenham()
