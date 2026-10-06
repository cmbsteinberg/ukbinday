"""Belfast: submit an ASP.NET postcode form, select a UPRN, then parse its collection table."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    find_tag,
    match_address,
    soup,
    text_of,
)

TITLE = "Belfast City Council"
URL = "https://online.belfastcity.gov.uk/find-bin-collection-day"
API_URL = URL + "/Default.aspx"
REQUEST_TIMEOUT = 30


def _parse_schedule(html: str) -> list[Collection]:
    page = soup(html)
    table = find_tag(page, "table", {"id": "ItemsGrid"}, what="Could not find Belfast's bin collection schedule table")

    collections: list[Collection] = []
    for row in table.find_all("tr")[1:]:
        columns = row.find_all("td")
        if len(columns) != 4:
            continue

        bin_type = columns[0].get_text(strip=True)
        collection_text = re.sub(r"\s+", " ", columns[3].get_text(strip=True))
        try:
            collection_date = datetime.strptime(collection_text, "%a %b %d %Y").date()
        except ValueError:
            continue
        collections.append(Collection(collection_date, bin_type))

    if not collections:
        raise InputError("No Belfast bin collection entries found")
    return collections


class Belfast(Scraper):
    meta = Meta(
        title=TITLE,
        url=URL,
        lads=("N09000003",),
        cases={
            "Test_1": {"postcode": "BT9 6DG", "uprn": "185075148"},
            "Test_2": {"postcode": "BT9 6DG"},
        },
    )
    requires = frozenset({"postcode"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").strip().upper()

        response = await http.get(API_URL, timeout=REQUEST_TIMEOUT)
        page = soup(response.text)
        viewstate = find_tag(page, "input", {"name": "__VIEWSTATE"})["value"]
        viewstate_generator = find_tag(page, "input", {"name": "__VIEWSTATEGENERATOR"})["value"]
        event_validation = find_tag(page, "input", {"name": "__EVENTVALIDATION"})["value"]

        postcode_data = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstate_generator,
            "__SCROLLPOSITIONX": "0",
            "__SCROLLPOSITIONY": "0",
            "__EVENTVALIDATION": event_validation,
            "ctl00$MainContent$searchBy_radio": "P",
            "ctl00$MainContent$Street_textbox": "",
            "ctl00$MainContent$Postcode_textbox": postcode,
            "ctl00$MainContent$AddressLookup_button": "Find address",
        }
        response = await http.post(API_URL, data=postcode_data, timeout=REQUEST_TIMEOUT)

        page = soup(response.text)
        error_message = page.find("span", {"id": "lblPostcodeError"})
        if error_message and error_message.get("style") != "display:none":
            raise InputError(f"Error from Belfast's website: {text_of(error_message)}")

        viewstate = find_tag(page, "input", {"name": "__VIEWSTATE"})["value"]
        viewstate_generator = find_tag(page, "input", {"name": "__VIEWSTATEGENERATOR"})["value"]
        event_validation = find_tag(page, "input", {"name": "__EVENTVALIDATION"})["value"]

        address_select = page.find("select", {"id": "lstAddresses"})
        if address_select is None:
            raise AddressNotFound(f"No addresses found for postcode: {postcode}")

        valid_options = [
            option
            for option in address_select.find_all("option")
            if not text_of(option).startswith("Select")
        ]
        if address.uprn:
            uprn = address.uprn
        elif address.first_line or (address.house_number and address.street):
            option = match_address(
                address,
                valid_options,
                text=text_of,
                uprn=lambda candidate: candidate.get("value"),
            )
            uprn = option["value"]
        else:
            if not valid_options:
                raise AddressNotFound(f"No valid addresses found for postcode: {postcode}")
            uprn = valid_options[0]["value"]

        address_data = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstate_generator,
            "__SCROLLPOSITIONX": "0",
            "__SCROLLPOSITIONY": "0",
            "__EVENTVALIDATION": event_validation,
            "ctl00$MainContent$searchBy_radio": "P",
            "ctl00$MainContent$Street_textbox": "",
            "ctl00$MainContent$Postcode_textbox": postcode,
            "ctl00$MainContent$lstAddresses": uprn,
            "ctl00$MainContent$SelectAddress_button": "Select address",
        }
        response = await http.post(API_URL, data=address_data, timeout=REQUEST_TIMEOUT)
        return _parse_schedule(response.text)


SCRAPER = Belfast()
