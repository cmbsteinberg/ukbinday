"""Rochford: submit a postcode, select its UPRN option, then retrieve collection dates."""

from __future__ import annotations

from datetime import datetime

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

API_URL = "https://www.rochford.gov.uk/bins-and-collections"
FORM_ID = "waste_collection_block_ajax_form"
AJAX_URL = f"{API_URL}?_wrapper_format=drupal_ajax&ajax_form=1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": API_URL,
}


def _get_form_build_id(html: str) -> str:
    field = soup(html).find("input", {"name": "form_build_id"})
    value = field.get("value") if isinstance(field, Tag) else None
    if not isinstance(value, str):
        raise UpstreamError("Rochford's form has no form_build_id")
    return value


def _get_insert_html(commands: list[object]) -> str:
    for command in commands:
        if isinstance(command, dict) and command.get("command") == "insert":
            data = command.get("data", "")
            return data if isinstance(data, str) else ""
    return ""


def _option_uprn(option: Tag) -> str | None:
    value = option.get("value")
    if isinstance(value, str):
        return value.rsplit("-", 1)[-1]
    return None


class Rochford(Scraper):
    meta = Meta(
        title="Rochford District Council",
        url="https://www.rochford.gov.uk",
        lads=("E07000075",),
        cases={
            "Station View, Rochford": {"postcode": "SS4 1AS", "uprn": "10014203194"},
            "Windermere Ave, Hullbridge": {"postcode": "SS5 6JT", "uprn": "100090575867"},
        },
    )
    requires = frozenset({"postcode"})

    headers = HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").upper()

        # Step 0 - load page and scrape the initial form_build_id.
        r = await http.get(API_URL)
        form_build_id = _get_form_build_id(r.text)

        # Step 1 - submit postcode to obtain the address dropdown.
        payload = {
            "postcode": postcode,
            "op": "Find",
            "form_build_id": form_build_id,
            "form_id": FORM_ID,
            "_triggering_element_name": "op",
            "_triggering_element_value": "Find",
            "_drupal_ajax": "1",
        }
        r = await http.post(AJAX_URL, data=payload)
        insert_html = _get_insert_html(r.json())
        page = soup(insert_html)

        select = page.find("select", {"name": "uprn"})
        options = [
            option
            for option in select.find_all("option")
            if isinstance(option, Tag) and isinstance(option.get("value"), str) and option.get("value")
        ] if isinstance(select, Tag) else []

        if not options:
            raise AddressNotFound(f"Rochford has no properties listed for postcode {postcode}")

        selected = match_address(
            address,
            options,
            text=lambda option: option.get_text(" ", strip=True),
            uprn=_option_uprn,
        )
        selected_uprn = selected.get("value")
        if not isinstance(selected_uprn, str):
            raise UpstreamError("Rochford returned a property option without a UPRN")

        # form_build_id rotates - re-scrape it from the step 1 response.
        rotated_build_id = _get_form_build_id(insert_html)

        # Step 2 - submit the chosen uprn to get the collection days.
        payload = {
            "postcode": postcode,
            "uprn": selected_uprn,
            "op": "View collection days",
            "form_build_id": rotated_build_id,
            "form_id": FORM_ID,
            "_triggering_element_name": "op",
            "_triggering_element_value": "View collection days",
            "_drupal_ajax": "1",
        }
        r = await http.post(AJAX_URL, data=payload)
        insert_html = _get_insert_html(r.json())
        page = soup(insert_html)

        collections: list[Collection] = []
        for row in page.find_all("tr", {"class": "waste-collection__day"}):
            time_tag = row.find("time")
            type_cell = row.find("td", {"class": "waste-collection__day--type"})
            if not isinstance(time_tag, Tag) or not isinstance(type_cell, Tag):
                continue
            date_value = time_tag.get("datetime")
            if not isinstance(date_value, str):
                continue
            collections.append(
                Collection(
                    date=datetime.strptime(date_value, "%Y-%m-%d").date(),
                    type=type_cell.get_text(strip=True),
                )
            )

        return collections


SCRAPER = Rochford()
