"""High Peak: search the Bartec dashboard by postcode, then select a premises by UPRN."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_LOGGER = logging.getLogger(__name__)

_API_URL = "https://bins.highpeak.gov.uk/PublicDashboard"
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
        raise UpstreamError("Could not find verification token on High Peak bin day lookup page.")
    return match.group(1)


def _extract_json_blocks(html: str) -> list[list[dict[str, object]]]:
    blocks: list[list[dict[str, object]]] = []
    for raw in _DATASOURCE_REGEX.findall(html):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            blocks.append([item for item in data if isinstance(item, dict)])
    return blocks


class HighPeak(Scraper):
    meta = Meta(
        title="High Peak Borough Council",
        url="https://www.highpeak.gov.uk/",
        lads=("E07000037",),
        cases={
            "SK23 6BQ 10010724045": {"postcode": "SK23 6BQ", "uprn": "10010724045"},
            "S33 7ZA, 10010747174": {"postcode": "S33 7ZA", "uprn": "10010747174"},
            "SK13 2AD, 10010734345": {"postcode": "SK13 2AD", "uprn": "10010734345"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").strip()
        uprn = address.need("uprn").strip()

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
            raise AddressNotFound(f"High Peak has no premises for postcode {postcode}")

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
                f"High Peak has no schedule for UPRN {uprn}",
                suggestions=known_uprns,
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
                _LOGGER.warning("Could not parse date %s", date_str)
                continue

            collections.append(Collection(date=day, type=str(subject)))

        return collections


SCRAPER = HighPeak()
