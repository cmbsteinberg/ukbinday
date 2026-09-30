"""Scottish Borders: search by postcode, select the supplied UPRN, then parse the calendar page."""

from __future__ import annotations

import json
import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

URL = "https://scotborders-live-portal.bartecmunicipal.com/Embeddable/CollectionCalendar"
_ORIGIN = "https://scotborders-live-portal.bartecmunicipal.com"
_DATA_PATTERN = re.compile(
    r'dataSource":\s*ejs\.data\.DataUtil\.parse\.isJson\(\s*(\[.*?\])\s*\)',
    re.DOTALL,
)


def _get_token(html: str) -> str:
    match = re.search(
        r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"',
        html,
    )
    if match:
        return match.group(1)
    match = re.search(
        r"name='__RequestVerificationToken' type='hidden' value='([^']+)'",
        html,
    )
    if match:
        return match.group(1)
    raise UpstreamError("Could not find verification token")


class ScottishBorders(Scraper):
    meta = Meta(
        title="Scottish Borders Council",
        url=URL,
        lads=("S12000026",),
        cases={"Test": {"uprn": "116073632", "postcode": "TD9 9HL"}},
    )
    requires = frozenset({"uprn", "postcode"})
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": URL,
        "Origin": _ORIGIN,
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        uprn = address.need("uprn")

        r1 = await http.get(URL)
        token = _get_token(r1.text)

        r2 = await http.post(
            f"{URL}?handler=SearchPostcode",
            data={
                "__RequestVerificationToken": token,
                "SelectedPostcode": postcode,
            },
        )
        token = _get_token(r2.text)

        r3 = await http.post(
            f"{URL}?handler=SelectPrem",
            data={
                "__RequestVerificationToken": token,
                "SelectedPostcode": postcode,
                "SelectedPremises": uprn,
            },
        )

        matches = _DATA_PATTERN.findall(r3.text)
        if not matches:
            raise UpstreamError("No JSON data blocks found in page source")

        collections: list[Collection] = []
        found_valid_block = False

        for json_str in matches:
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            if not isinstance(data, list) or not data:
                continue
            if "Subject" not in data[0]:
                continue

            found_valid_block = True
            for item in data:
                subject = item.get("Subject")
                date_str = item.get("StartTime")
                if not subject or not date_str:
                    continue

                try:
                    day = datetime.fromisoformat(date_str).date()
                except ValueError:
                    day = datetime.strptime(date_str.split("T")[0], "%Y-%m-%d").date()

                collections.append(Collection(day, subject))
            break

        if not found_valid_block:
            raise UpstreamError("Found JSON blocks, but none contained bin schedule data")

        return collections


SCRAPER = ScottishBorders()
