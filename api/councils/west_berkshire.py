"""West Berkshire: find a UPRN by postcode when needed, then request each collection date."""

from __future__ import annotations

import json
import time
from datetime import date, datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
)

_SEARCH_URL = "https://www.westberks.gov.uk/apiserver/ajaxlibrary"


def _fix_date(day: date) -> date:
    if datetime.now().month == 12 and day.month in (1, 2):
        return day.replace(year=day.year + 1)
    return day


class WestBerkshire(Scraper):
    meta = Meta(
        title="West Berkshire Council",
        url="https://westberks.gov.uk",
        lads=("E06000037",),
        cases={
            "known_uprn": {"uprn": "100080241094"},
            "unknown_uprn_by_name": {"postcode": "RG7 6NZ", "house_number": "PARROG HOUSE"},
            "unknown_uprn_by_number": {"postcode": "RG18 4QU", "house_number": "6"},
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn: object | None = address.uprn.zfill(12) if address.uprn is not None else None

        if uprn is None:
            if address.postcode is None:
                raise InputError("West Berkshire needs a UPRN or postcode and address")
            if address.first_line is None:
                raise InputError("West Berkshire needs a UPRN or postcode and address")

            jsonrpc = {
                "id": str(int(time.time())),
                "method": "location.westberks.echoPostcodeFinder",
                "params": {"provider": "", "postcode": address.postcode.strip()},
            }
            params = {"callback": "HomeAssistant", "jsonrpc": json.dumps(jsonrpc), "_": 0}
            response = await http.get(_SEARCH_URL, params=params)

            response_str = response.content.decode("utf-8")
            data_length = len(response_str) - 1
            response_sub = response_str[14:data_length]
            address_data = json.loads(response_sub)
            candidates = address_data["result"]
            uprn = match_address(
                address,
                candidates,
                text=lambda candidate: candidate["line1"],
                uprn=lambda candidate: candidate["udprn"],
            )["udprn"]

        collections: list[Collection] = []
        requests = [
            ("Rubbish", "getNextRubbishCollectionDate", "nextRubbishDateText", "nextRubbishDateSubText"),
            ("Recycling", "getNextRecyclingCollectionDate", "nextRecyclingDateText", "nextRecyclingDateSubText"),
            ("FoodWaste", "getNextFoodWasteCollectionDate", "nextFoodWasteDateText", "nextFoodWasteDateSubText"),
        ]

        for waste_type, method, text_key, sub_key in requests:
            payload = {
                "jsonrpc": "2.0",
                "id": str(int(time.time())),
                "method": f"goss.echo.westberks.forms.{method}",
                "params": {"uprn": uprn},
            }
            response = await http.post(_SEARCH_URL, json=payload)
            data = json.loads(response.content)

            result = data.get("result", {})
            dt_str = result.get(sub_key, "").strip() or result.get(text_key, "").strip()
            if not dt_str:
                continue
            dt_str += " " + str(date.today().year)
            try:
                day = datetime.strptime(dt_str, "%A %d %B %Y").date()
            except ValueError:
                continue
            collections.append(Collection(_fix_date(day), waste_type))

        return collections


SCRAPER = WestBerkshire()
