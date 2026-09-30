"""Neath Port Talbot: submit a postcode, then its UPRN, to retrieve bin dates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
    soup,
    text_of,
)

URL = "https://www.npt.gov.uk/"
_BASE_URL = f"{URL}bins-and-recycling/equipment-and-collections/bin-day-finder/"
_DAY_MONTH_RE = re.compile(
    r"(?i)^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s*(\d{1,2})\s*([A-Za-z]+)\s*$"
)


@dataclass(frozen=True)
class _Tokens:
    request_verification_token: str | None
    ufprt: str | None


def _clean_text(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _extract_tokens(raw_html: str) -> _Tokens:
    page = soup(raw_html)
    request_token = page.find("input", {"name": "__RequestVerificationToken"})
    ufprt_input = page.find("input", {"name": "ufprt"})
    if not isinstance(request_token, Tag):
        raise UpstreamError("Failed to find __RequestVerificationToken in HTML.")
    if not isinstance(ufprt_input, Tag):
        raise UpstreamError("Failed to find ufprt in HTML.")

    request_verification_token = request_token.get("value")
    ufprt = ufprt_input.get("value")
    return _Tokens(
        str(request_verification_token) if request_verification_token else None,
        str(ufprt) if ufprt else None,
    )


def _base_post_payload(raw_html: str) -> dict[str, str | None]:
    tokens = _extract_tokens(raw_html)
    return {
        "__RequestVerificationToken": tokens.request_verification_token,
        "ufprt": tokens.ufprt,
    }


def _parse_collections(raw_html: str) -> list[Collection]:
    page = soup(raw_html)
    root = page.find(id="contentInner")
    if not isinstance(root, Tag):
        raise UpstreamError("Neath Port Talbot bin page has no contentInner element.")

    headers = [
        header
        for header in root.find_all("h2")
        if _DAY_MONTH_RE.match(_clean_text(header.get_text()))
    ]

    collections: list[Collection] = []
    for header in headers:
        collection_date = parse_date(_clean_text(header.get_text()))

        for sibling in header.next_siblings:
            if not isinstance(sibling, Tag):
                continue
            if sibling.name == "h2":
                break

            for card in sibling.find_all(class_="card"):
                link = card.find("a")
                if not isinstance(link, Tag):
                    continue

                type_text = _clean_text(text_of(link))
                if type_text:
                    collections.append(Collection(collection_date, type_text))

    if not collections:
        raise UpstreamError("No waste collection entries found on the Neath Port Talbot page.")
    return collections


class NeathPortTalbot(Scraper):
    meta = Meta(
        title="Neath Port Talbot Council",
        url=URL,
        lads=("W06000012",),
        cases={
            "Test_001": {"postcode": "SA11 3HW", "uprn": "100100601042"},
            "Test_002": {"postcode": "SA11 3HY", "uprn": "100100599841"},
            "Test_003": {"postcode": "SA11 3DY", "uprn": "100100600279"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": _BASE_URL,
        "Origin": URL,
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        initial_request = await http.get(_BASE_URL, timeout=20)

        fetch_addresses_payload = {
            **_base_post_payload(initial_request.text),
            "PostCode": address.need("postcode"),
            "action": "Find address",
        }
        fetch_addresses_request = await http.post(
            _BASE_URL,
            data=fetch_addresses_payload,
            timeout=20,
        )

        fetch_collections_payload = {
            **_base_post_payload(fetch_addresses_request.text),
            "Address": address.need("uprn").zfill(12),
            "action": "Show my bin days",
        }
        fetch_collections_request = await http.post(
            _BASE_URL,
            data=fetch_collections_payload,
            timeout=20,
        )

        return _parse_collections(fetch_collections_request.text)


SCRAPER = NeathPortTalbot()
