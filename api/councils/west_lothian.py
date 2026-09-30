"""West Lothian: submit the UPRN and postcode to the bin-collections form, then parse its iCalendar or page data."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    parse_ics,
    soup,
)

_COLLECTION_PAGE_URL = "https://www.westlothian.gov.uk/bin-collections"
_VARIABLES_PATTERN = re.compile(
    r'var WLBINCOLLECTIONSerializedVariables = "(.*?)";$',
    re.MULTILINE | re.DOTALL,
)
_FORM_DATA_PATTERN = re.compile(
    r'var WLBINCOLLECTIONFormData = "(.*?)";$',
    re.MULTILINE | re.DOTALL,
)


def _get_goss_form_ids(url: str) -> dict[str, str]:
    values = parse_qs(urlparse(url).query)
    try:
        return {
            "page_session_id": values["pageSessionId"][0],
            "session_id": values["fsid"][0],
            "nonce": values["fsn"][0],
        }
    except (KeyError, IndexError) as exc:
        raise UpstreamError("West Lothian form is missing its session identifiers") from exc


def _decode_embedded_info(markup: str, pattern: re.Pattern[str], name: str) -> dict[str, object]:
    page = soup(markup)
    script = next(
        (
            tag
            for tag in page.find_all("script")
            if isinstance(tag, Tag) and pattern.search(tag.text or "")
        ),
        None,
    )
    if script is None:
        raise UpstreamError(f"West Lothian page is missing {name}")

    match = pattern.search(script.text or "")
    if match is None:
        raise UpstreamError(f"West Lothian page has invalid {name}")
    try:
        decoded = base64.b64decode(match.group(1))
        result = json.loads(decoded)
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpstreamError(f"West Lothian page has invalid {name}") from exc
    if not isinstance(result, dict):
        raise UpstreamError(f"West Lothian page has invalid {name}")
    return result


def _get_ical_bin_collection_info(markup: str) -> dict[str, object]:
    return _decode_embedded_info(markup, _VARIABLES_PATTERN, "WLBINCOLLECTIONSerializedVariables")


def _get_immediate_bin_collection_info(markup: str) -> dict[str, object]:
    return _decode_embedded_info(markup, _FORM_DATA_PATTERN, "WLBINCOLLECTIONFormData")


async def _get_address_page(http: Http) -> str:
    response = await http.get(_COLLECTION_PAGE_URL)
    return response.text


async def _get_bin_collection_info_page(
    http: Http,
    address_page: str,
    postcode: str,
    uprn: str,
) -> str:
    page = soup(address_page)
    form = page.find(id="WLBINCOLLECTION_FORM")
    if not isinstance(form, Tag) or not form.get("action"):
        raise UpstreamError("West Lothian bin-collections page has no lookup form")

    action = form["action"]
    goss_ids = _get_goss_form_ids(action)
    response = await http.post(
        action,
        follow_redirects=True,
        data={
            "WLBINCOLLECTION_PAGESESSIONID": goss_ids["page_session_id"],
            "WLBINCOLLECTION_SESSIONID": goss_ids["session_id"],
            "WLBINCOLLECTION_NONCE": goss_ids["nonce"],
            "WLBINCOLLECTION_VARIABLES": "e30=",
            "WLBINCOLLECTION_PAGENAME": "PAGE1",
            "WLBINCOLLECTION_PAGEINSTANCE": "0",
            "WLBINCOLLECTION_PAGE1_UPRN": uprn,
            "WLBINCOLLECTION_PAGE1_ADDRESSLOOKUPPOSTCODE": postcode,
            "WLBINCOLLECTION_PAGE1_ADDRESSLOOKUPADDRESS": "4",
            "WLBINCOLLECTION_FORMACTION_NEXT": "WLBINCOLLECTION_PAGE1_NAVBUTTONS",
        },
    )
    return response.text


def _generate_collection_entries(info: dict[str, object]) -> list[Collection]:
    ical_content = info.get("ICALCONTENT")
    webpage_content = info.get("PAGE2_1")

    if ical_content is not None:
        if not isinstance(ical_content, dict):
            raise UpstreamError("West Lothian returned invalid iCalendar data")
        error = ical_content.get("error")
        if error is not None:
            raise UpstreamError(str(error))

        value = ical_content.get("value")
        if not isinstance(value, str):
            raise UpstreamError("West Lothian returned invalid iCalendar data")
        ics_data = re.sub(r"UNTIL=(\d{8})(?![T\d])", r"UNTIL=\1T000000", value)
        ics_data = re.sub(r"UNTIL=(\d{8}T\d{6})Z", r"UNTIL=\1", ics_data)
        try:
            events = parse_ics(ics_data)
        except ValueError as exc:
            raise UpstreamError("West Lothian returned invalid iCalendar data") from exc
        return [Collection(event.date, event.summary) for event in events]

    if webpage_content is not None:
        if not isinstance(webpage_content, dict):
            raise UpstreamError("West Lothian returned invalid collection data")
        raw_collections = webpage_content.get("COLLECTIONS")
        if not raw_collections:
            return []
        try:
            collections = json.loads(raw_collections)
        except (json.JSONDecodeError, TypeError) as exc:
            raise UpstreamError("West Lothian returned invalid collection data") from exc
        if not isinstance(collections, list):
            raise UpstreamError("West Lothian returned invalid collection data")

        entries = []
        for item in collections:
            if not isinstance(item, dict):
                continue
            try:
                day = datetime.strptime(item["nextCollectionISO"], "%Y-%m-%d").date()
                bin_type = item["binType"]
            except (KeyError, TypeError, ValueError) as exc:
                raise UpstreamError("West Lothian returned invalid collection data") from exc
            entries.append(Collection(day, bin_type))
        return entries

    raise UpstreamError("West Lothian returned no collection data")


class WestLothian(Scraper):
    meta = Meta(
        title="West Lothian Council",
        url=_COLLECTION_PAGE_URL,
        lads=("S12000040",),
        cases={
            "Test_001": {"postcode": "EH48 4DD", "uprn": "135007799"},
            "Test_002": {"postcode": "EH55 8FJ", "uprn": "135051417"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    transport = Transport.CURL_CFFI
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Host": "www.westlothian.gov.uk",
        "Sec-Fetch-User": "?1",
        "Accept-Language": "en-GB,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "westlothian.gov.uk",
        "Cache-Control": "no-cache",
        "DNT": "1",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        address_page = await _get_address_page(http)
        info_page = await _get_bin_collection_info_page(
            http,
            address_page,
            address.need("postcode"),
            address.need("uprn"),
        )
        info = _get_ical_bin_collection_info(info_page)

        ical_content = info.get("ICALCONTENT")
        value = ical_content.get("value", {}) if isinstance(ical_content, dict) else {}
        if (
            isinstance(value, dict) and value.get("error") is not None
        ) or (
            isinstance(value, str) and "BEGIN:VCALENDAR" not in value
        ):
            info = _get_immediate_bin_collection_info(info_page)

        return _generate_collection_entries(info)


SCRAPER = WestLothian()
