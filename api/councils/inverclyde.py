"""Inverclyde: search a postcode for an address, then request its bin collections from the map service."""

from __future__ import annotations

import re
from datetime import date

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
    match_address,
    parse_date,
)

_API_BASE = "https://maps.inverclyde.gov.uk/noticeboard8"
_QUICKSEARCH_URL = f"{_API_BASE}/quicksearch.asmx/GetMoreResults"
_LOCALKNOWLEDGE_URL = f"{_API_BASE}/LocalKnowledge.asmx/AboutTheLocationForOverlay"

_ADDRESS_SEARCH_ID = 7
_LOCAL_KNOWLEDGE_ID = 3
_BIN_COLLECTIONS_OVERLAY_NO = 20

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{_API_BASE}/noticeboard.aspx",
}

_BIN_ALT_TEXT_PATTERN = re.compile(r'alt="Image of an? (\w+) bin"', re.IGNORECASE)
_DATE_PATTERN = re.compile(r"[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)\s+[A-Za-z]+\s+\d{4}")

_BIN_NAME_MAP = {
    "black": "General Waste",
    "grey": "General Waste",
    "food": "Food Waste",
    "blue": "Recycling",
    "brown": "Garden Waste",
}


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    match = _DATE_PATTERN.search(text)
    if not match:
        return None
    try:
        return parse_date(match.group(0))
    except (ValueError, OverflowError):
        return None


def _address_text(columns: dict[str, str]) -> str:
    return columns.get("RESULTS", "").split("\r\n")[0].strip()


class Inverclyde(Scraper):
    meta = Meta(
        title="Inverclyde Council",
        url="https://www.inverclyde.gov.uk",
        lads=("S12000018",),
        cases={
            "1 Findhorn Crescent": {
                "postcode": "PA16 0FG",
                "house_number": "1",
                "street": "Findhorn Crescent",
            },
            "1 Merrylee Avenue": {
                "postcode": "PA14 5UT",
                "house_number": "1",
                "street": "Merrylee Avenue",
            },
            "10 St John's Road": {
                "postcode": "PA19 1PL",
                "house_number": "10",
                "street": "St John's Road",
            },
        },
    )
    requires = frozenset({"postcode"})
    headers = _HEADERS
    verify_tls = False
    # The server only speaks TLS 1.2 RSA key exchange, which httpx/OpenSSL at the default
    # security level rejects; curl_cffi's TLS stack accepts it.
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        first_line = address.first_line
        if not first_line:
            raise InputError("Inverclyde needs an address")

        r = await http.post(
            _QUICKSEARCH_URL,
            headers=_HEADERS,
            timeout=30,
            json={
                "searchId": _ADDRESS_SEARCH_ID,
                "filter": address.need("postcode"),
                "startIndex": 0,
                "endIndex": 199,
            },
        )
        results = r.json().get("d", {}).get("Data") or []

        candidates: list[dict[str, str]] = []
        for item in results:
            columns = {c["Name"]: c["Value"] for c in item.get("Columns", [])}
            candidates.append(columns)

        matched_columns = match_address(
            address,
            candidates,
            text=_address_text,
            uprn=lambda columns: columns.get("UPRN"),
        )

        r = await http.post(
            _LOCALKNOWLEDGE_URL,
            headers=_HEADERS,
            timeout=30,
            json={
                "localKnowledgeID": _LOCAL_KNOWLEDGE_ID,
                "overlayNo": _BIN_COLLECTIONS_OVERLAY_NO,
                "x": matched_columns["E"],
                "y": matched_columns["N"],
            },
        )
        data = r.json().get("d") or {}

        attributes: dict[str, str] = {}
        for fmn in data.get("FMNResults") or []:
            for item in fmn.get("Items") or []:
                for attr in item.get("Attributes") or []:
                    attributes[attr["Name"]] = attr.get("Value", "")

        collections: list[Collection] = []
        for date_key, graphic_key in (
            ("top_bin_date2", "top_bin_graphic"),
            ("bottom_bin_date2", "bottom_bin_graphic"),
        ):
            collection_date = _parse_date(attributes.get(date_key))
            if collection_date is None:
                continue

            graphic = attributes.get(graphic_key, "")
            for colour in _BIN_ALT_TEXT_PATTERN.findall(graphic):
                colour = colour.lower()
                name = _BIN_NAME_MAP.get(colour, f"{colour.title()} Bin")
                collections.append(Collection(collection_date, name))

        return collections


SCRAPER = Inverclyde()
