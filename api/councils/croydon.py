"""Croydon: search by postcode, select the address, then submit the form for its collection schedule."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
    soup,
    text_of,
)

_BASE_URL = "https://service.croydon.gov.uk"
_CSRF_PATH = "/wasteservices/w/webpage/bin-day-enter-address"
_SEARCH_PATH = (
    "/wasteservices/w/webpage/bin-day-enter-address"
    "?webpage_subpage_id=PAG0000898EECEC1"
    "&webpage_token=faab02e1f62a58f7bad4c2ae5b8622e19846b97dde2a76f546c4bb1230cee044"
    "&widget_action=fragment_action"
)
_SCHEDULE_PATH = (
    "/wasteservices/w/webpage/bin-day-enter-address"
    "?webpage_subpage_id=PAG0000898EECEC1"
    "&webpage_token=faab02e1f62a58f7bad4c2ae5b8622e19846b97dde2a76f546c4bb1230cee044"
)

_HEADERS = {
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Host": "service.croydon.gov.uk",
    "Origin": _BASE_URL,
    "sec-ch-ua": '"Not_A Brand";v="99", "Google Chrome";v="109", "Chromium";v="109"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "Windows",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
    ),
}
_GET_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
    ),
    "Sec-Fetch-Mode": "none",
}
_POST_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Sec-Fetch-Mode": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}
_SESSION_STORAGE = {
    "destination_stack": [
        "w/webpage/bin-day-enter-address",
        "w/webpage/your-bin-collection-details?context_record_id=86086077"
        "&webpage_token=5c047b2c10b4aad66bef2054aac6bea52ad7a5e185ffdf7090b01f8ddc96728f",
        "w/webpage/bin-day-enter-address",
        "w/webpage/your-bin-collection-details?context_record_id=86085229"
        "&webpage_token=cf1b8fd6213f4823277d98c1dd8a992e6ebef1fabc7d892714e5d9dade448c37",
        "w/webpage/bin-day-enter-address",
        "w/webpage/your-bin-collection-details?context_record_id=86084221"
        "&webpage_token=7f52fb51019bf0e6bfe9647b1b31000124bd92a9d95781f1557f58b3ed40da52",
        "w/webpage/bin-day-enter-address",
        "w/webpage/your-bin-collection-details?context_record_id=86083209"
        "&webpage_token=de50c265da927336f526d9d9a44947595c3aa38965aa8c495ac2fb73d272ece8",
        "w/webpage/bin-day-enter-address",
    ],
    "last_context_record_id": "86086077",
}


def _address_text(candidate: dict[str, Any]) -> str:
    return str(candidate["address_single_line"])


class Croydon(Scraper):
    meta = Meta(
        title="Croydon Council",
        url="https://croydon.gov.uk",
        lads=("E09000008",),
        cases={
            "Test_001": {"postcode": "CR0 6LN", "house_number": "64", "street": "Coniston Road"},
            "Test_002": {"postcode": "SE25 5BU", "house_number": "23B", "street": "Howard Road"},
            "Test_003": {"postcode": "CR0 6EG", "house_number": "48", "street": "Exeter Road"},
        },
    )
    requires = frozenset({"postcode"})

    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        if address.first_line is None and address.label is None:
            raise InputError("Croydon needs an address as well as a postcode")

        # Get token
        url = _BASE_URL + _CSRF_PATH
        r0 = await http.get(url, headers=_GET_HEADERS)

        page = soup(r0.text)
        app_body = page.find("div", {"class": "app-body"})
        script = text_of(app_body.find("script", {"type": "text/javascript"}))
        match = re.search(r"var CSRF = ('|\")(.*?)('|\" );", script)
        if match is None:
            match = re.search(r"""var CSRF = ('|")(.*?)('|");""", script)
        csrf_token = match.groups()[1]

        # Get additional tokens
        form_data = {
            "_dummy": "1",
            "_session_storage": '{"_global":{}}',
            "_update_page_content_request": "1",
            "form_check_ajax": csrf_token,
        }
        r1 = await http.post(
            _BASE_URL + _CSRF_PATH,
            headers=_POST_HEADERS,
            data=form_data,
        )

        page_data = r1.json()["data"]
        key = (
            re.findall(r'data-unique_key="C_[a-f0-9]+"', page_data)[-1]
            .replace('data-unique_key="', "")
            .replace('"', "")
        )
        page = soup(page_data)
        submitted_widget_group_id = page.find_all(
            "input", {"name": "submitted_widget_group_id"}
        )[-1].attrs["value"]
        submission_token = page.find("input", {"name": "submission_token"}).attrs["value"]
        submitted_page_id = page.find("input", {"name": "submitted_page_id"}).attrs["value"]

        # Use postcode and address to find address
        url = _BASE_URL + _SEARCH_PATH
        form_data = {
            "code_action": "search",
            "code_params": '{"search_item":"' + postcode + '","is_ss":true}',
            "fragment_action": "handle_event",
            "fragment_id": "PCF0020408EECEC1",
            "fragment_collection_class": "formtable",
            "fragment_collection_editable_values": '{"PCF0021449EECEC1":"1"}',
            "_session_storage": json.dumps(
                {
                    "/wasteservices/w/webpage/bin-day-enter-address": {},
                    "_global": _SESSION_STORAGE,
                }
            ),
            "action_cell_id": "PCL0005629EECEC1",
            "action_page_id": "PAG0000898EECEC1",
            "form_check_ajax": csrf_token,
        }
        r2 = await http.post(url, headers=_POST_HEADERS, data=form_data)

        addresses: list[dict[str, Any]] = r2.json()["response"]["items"]
        selected_address = match_address(
            address,
            addresses,
            text=_address_text,
        )
        address_id = str(selected_address["id"])

        # Use address ID to get schedule
        url = _BASE_URL + _SCHEDULE_PATH
        form_data = {
            "form_check": csrf_token,
            "submitted_page_id": submitted_page_id,
            "submitted_widget_group_id": submitted_widget_group_id,
            "submitted_widget_group_type": "modify",
            "submission_token": submission_token,
            f"payload[PAG0000898EECEC1][PWG0002644EECEC1][PCL0005629EECEC1][formtable][{key}][PCF0020408EECEC1]": address_id,
            f"payload[PAG0000898EECEC1][PWG0002644EECEC1][PCL0005629EECEC1][formtable][{key}][PCF0021449EECEC1]": "1",
            f"payload[PAG0000898EECEC1][PWG0002644EECEC1][PCL0005629EECEC1][formtable][{key}][PCF0020072EECEC1]": "Next",
            "submit_fragment_id": "PCF0020072EECEC1",
            "_session_storage": json.dumps({"_global": _SESSION_STORAGE}),
            "_update_page_content_request": 1,
            "form_check_ajax": csrf_token,
        }
        r3 = await http.post(url, headers=_POST_HEADERS, data=form_data)
        json_response = r3.json()

        url = _BASE_URL + json_response["redirect_url"]
        form_data = {
            "_dummy": 1,
            "_session_storage": json.dumps({"_global": _SESSION_STORAGE}),
            "_update_page_content_request": 1,
            "form_check_ajax": csrf_token,
        }
        r4 = await http.post(url, headers=_POST_HEADERS, data=form_data)

        collection_data = r4.json()["data"]
        page = soup(collection_data)
        schedule = page.find_all("div", {"class": "listing_template_record"})

        collections = []
        for pickup in schedule:
            waste_type = pickup.find_all(
                "div", {"class": "fragment_presenter_template_show"}
            )[0].text.strip()
            waste_date = pickup.find("span", {"class": "value-as-text"}).get_text(
                strip=True
            )
            collections.append(
                Collection(
                    date=datetime.strptime(waste_date, "%A %d %B %Y").date(),
                    type=waste_type,
                )
            )

        return collections


SCRAPER = Croydon()
