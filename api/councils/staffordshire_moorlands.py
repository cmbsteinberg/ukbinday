"""Staffordshire Moorlands: search the Bartec dashboard by postcode, then select premises by UPRN."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_API_URL = "https://bins.staffsmoorlands.gov.uk/PublicDashboard"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
_TOKEN_REGEX = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_DATASOURCE_REGEX = re.compile(
    r'dataSource":\s*ejs\.data\.DataUtil\.parse\.isJson\(\s*(\[.*?\])\s*\)',
    re.DOTALL,
)


def _get_token(html: str) -> str:
    match = _TOKEN_REGEX.search(html)
    if not match:
        raise UpstreamError(
            "Could not find verification token on Staffordshire Moorlands bin day lookup page."
        )
    return match.group(1)


def _extract_json_blocks(html: str) -> list[list[Any]]:
    blocks: list[list[Any]] = []
    for raw in _DATASOURCE_REGEX.findall(html):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            blocks.append(data)
    return blocks


class StaffordshireMoorlands(Scraper):
    meta = Meta(
        title="Staffordshire Moorlands District Council",
        url="https://www.staffsmoorlands.gov.uk",
        lads=("E07000198",),
        cases={
            "Managers Accommodation Roaring Meg": {
                "postcode": "ST8 7EA",
                "uprn": "10010602737",
            },
            "34 Pennine Way, Biddulph": {
                "postcode": "ST8 7EA",
                "uprn": "100031858191",
            },
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        uprn = address.need("uprn")

        r = await http.get(_API_URL)
        token = _get_token(r.text)

        r = await http.post(
            f"{_API_URL}?handler=SearchPostcode",
            data={
                "__RequestVerificationToken": token,
                "SelectedPostcode": postcode,
            },
        )
        token = _get_token(r.text)

        premises_blocks = [
            block
            for block in _extract_json_blocks(r.text)
            if block and "UPRN" in block[0]
        ]
        if not premises_blocks:
            raise AddressNotFound(f"No premises found for postcode {postcode}")

        known_uprns = sorted(
            {str(int(item["UPRN"])) for item in premises_blocks[0] if "UPRN" in item}
        )

        r = await http.post(
            f"{_API_URL}?handler=SelectPrem",
            data={
                "__RequestVerificationToken": token,
                "SelectedPostcode": postcode,
                "SelectedPremises": uprn,
            },
        )

        schedule_blocks = [
            block
            for block in _extract_json_blocks(r.text)
            if block and "Subject" in block[0]
        ]
        if not schedule_blocks:
            raise AddressNotFound(
                f"No collection schedule found for UPRN {uprn}",
                known_uprns,
            )

        collections: list[Collection] = []
        for item in schedule_blocks[0]:
            subject = item.get("Subject")
            date_str = item.get("StartTime")
            if not subject or not date_str:
                continue
            try:
                day = datetime.fromisoformat(date_str).date()
            except ValueError:
                continue
            collections.append(Collection(date=day, type=subject))

        return collections


SCRAPER = StaffordshireMoorlands()
