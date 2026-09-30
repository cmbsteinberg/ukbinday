"""Torridge: AchieveForms lookup keyed on the UPRN, returning bin types and collection dates."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from time import time_ns

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
)

BASE = "https://torridgedc-self.achieveservice.com"
HEADERS = {"user-agent": "Mozilla/5.0"}
BIN_NAME = {
    "Refuse": "Refuse",
    "Recycling": "Recycling",
    "GardenBin": "Garden",
}
RELATIVE_DATES = {"Today": 0, "Tomorrow": 1}


class Torridge(Scraper):
    meta = Meta(
        title="Torridge Council",
        url="https://torridge.gov.uk",
        lads=("E07000046",),
        cases={
            "Test_001": {"uprn": "10093911050"},
            "Test_002": {"uprn": "10002296087"},
            "Test_003": {"uprn": "200001644184"},
        },
    )
    requires = frozenset({"uprn"})
    headers = HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        await http.get(
            f"{BASE}/apibroker/domain/torridgedc-self.achieveservice.com"
            f"?_={time_ns() // 1_000_000}"
        )

        sid_request = await http.get(
            f"{BASE}/authapi/isauthenticated"
            "?uri=https%3A%2F%2Ftorridgedc-self.achieveservice.com%2Fservice%2FMy_property_information"
            "&hostname=torridgedc-self.achieveservice.com&withCredentials=true"
        )
        sid = sid_request.json()["auth-session"]

        schedule_request = await http.post(
            f"{BASE}/apibroker/runLookup"
            f"?id=6583107397653&repeat_against=&noRetry=false&getOnlyTokens=undefined"
            f"&log_id=&app_name=AF-Renderer::Self&_= {time_ns() // 1_000_000}&sid={sid}".replace("&_= ", "&_="),
            json={"formValues": {"Search": {"uprn": {"value": address.need("uprn")}}}},
        )
        rowdata = json.loads(schedule_request.content)["integration"]["transformed"]["rows_data"]

        entries: list[Collection] = []
        today = date.today()

        for item in rowdata.values():
            for _, value in item.items():
                parts = value.split(": ")
                if len(parts) < 2:
                    raise UpstreamError("Torridge returned an unexpected collection format")

                waste_type = parts[0].strip()
                if waste_type not in BIN_NAME:
                    raise UpstreamError(f"Torridge returned an unknown waste type: {waste_type}")
                waste_type = BIN_NAME[waste_type]

                date_part = parts[1].split(" then ")[0].strip()
                date_part = re.sub(r"\(.*?\)", "", date_part).strip()

                if not date_part:
                    raise UpstreamError("Torridge returned an unexpected collection date")
                if date_part.split()[0].lower() == "no":
                    continue

                if date_part in RELATIVE_DATES:
                    collection_date = today + timedelta(days=RELATIVE_DATES[date_part])
                else:
                    try:
                        collection_date = parse_date(date_part)
                    except ValueError as exc:
                        raise UpstreamError(
                            f"Torridge returned an unexpected collection date: {date_part}"
                        ) from exc

                entries.append(Collection(collection_date, waste_type))

        return entries


SCRAPER = Torridge()
