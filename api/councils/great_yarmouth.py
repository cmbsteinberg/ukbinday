"""Great Yarmouth: submit the UPRN to its waste form and parse the returned schedule."""

from __future__ import annotations

import base64
import json
import re

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    parse_date,
    soup,
)

_BASE_URL = "https://myaccount.great-yarmouth.gov.uk"
_FORM_NAME = "WASTECOLLECTIONCALENDARV2"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


class GreatYarmouth(Scraper):
    meta = Meta(
        title="Great Yarmouth Borough Council",
        url="https://myaccount.great-yarmouth.gov.uk/find-my-waste-collection-days",
        lads=("E07000145",),
        cases={
            "64 Black Street Martham NR29 4PR": {"uprn": "100090834016"},
            "1 Hobland Barns Bradwell NR31 9BS": {"uprn": "10023466513"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        # Get the form page and extract session tokens.
        response = await http.get(f"{_BASE_URL}/find-my-waste-collection-days")
        action_match = re.search(r'action="([^"]*processsubmission[^"]*)"', response.text)
        if not action_match:
            raise UpstreamError("Could not find form action URL on collection page")
        action = action_match.group(1).replace("&amp;", "&")

        page = soup(response.text)
        form = page.find("form", {"id": f"{_FORM_NAME}_FORM"})
        if not isinstance(form, Tag):
            raise UpstreamError("Could not find waste collection form on page")

        form_data = {
            name: field.get("value", "")
            for field in form.find_all("input")
            if isinstance((name := field.get("name")), str) and name
        }

        # Submit the form with the UPRN to retrieve the collection schedule.
        form_data.update(
            {
                f"{_FORM_NAME}_ADDRESS_UPRN": uprn,
                f"{_FORM_NAME}_ADDRESS_COUNTRY": "United Kingdom",
                f"{_FORM_NAME}_ADDRESS_ADDRESSKNOWN": "true",
                f"{_FORM_NAME}_ADDRESS_FINDANADDRESS": "true",
                f"{_FORM_NAME}_FORMACTION_NEXT": f"{_FORM_NAME}_ADDRESS_LOOKUPVBUTTON",
                f"{_FORM_NAME}_ADDRESS_LOOKUPVBUTTON": "Confirm Address",
            }
        )
        schedule_response = await http.post(action, data=form_data)

        # Extract the collection schedule from the Base64-encoded FormData.
        form_data_match = re.search(
            rf'var {_FORM_NAME}FormData = "([^"]+)"', schedule_response.text
        )
        if not form_data_match:
            raise UpstreamError("Could not find form data in the schedule response")

        form_data_json = json.loads(
            base64.b64decode(form_data_match.group(1)).decode("utf-8")
        )
        showschedule = form_data_json.get("LOOKUP_1", {}).get("SHOWSCHEDULE", "")
        if not showschedule:
            raise InputError(
                f"No collection schedule found for UPRN {uprn}. "
                "Ensure the UPRN is for a property within Great Yarmouth Borough."
            )

        # Parse the schedule HTML.
        schedule_page = soup(showschedule)
        collections: list[Collection] = []
        for div in schedule_page.find_all("div", class_="collection-area"):
            detail = div.find("div", class_="collection-detail")
            if not isinstance(detail, Tag):
                continue
            bold = detail.find("b")
            if not isinstance(bold, Tag):
                continue

            date_text = bold.get_text(strip=True)
            type_text = detail.get_text(separator=" ", strip=True).replace(date_text, "").strip()
            type_clean = re.sub(r"\s*will be emptied\s*$", "", type_text).strip()

            try:
                collection_date = parse_date(date_text)
            except ValueError:
                continue

            collections.append(Collection(collection_date, type_clean))

        return collections


SCRAPER = GreatYarmouth()
