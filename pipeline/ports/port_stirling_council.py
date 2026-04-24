from datetime import datetime, timedelta

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Stirling Council"
DESCRIPTION = "Source for stirling.gov.uk waste collection via Recollect API."
URL = "https://www.stirling.gov.uk"
TEST_CASES = {
    "Test_001": {"postcode": "FK9 4QA", "house_number": "5 Sunnylaw Road"},
}

RECOLLECT_BASE = "https://api.eu.recollect.net/api"
AREA = "StirlingUK"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}

ICON_MAP = {
    "REFUSE": "mdi:trash-can",
    "RECYCLING": "mdi:recycle",
    "GARDEN": "mdi:leaf",
    "PLASTIC": "mdi:recycle",
    "GLASS": "mdi:bottle-wine",
}


class Source:
    def __init__(
        self,
        postcode: str = "",
        house_number: str = "",
        uprn: str | int | None = None,
    ):
        self._postcode = postcode
        self._house_number = house_number

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers=HEADERS) as client:
            place_id = await self._resolve_place(client)
            now = datetime.now()
            after = now.strftime("%Y-%m-%d")
            before = (now + timedelta(days=90)).strftime("%Y-%m-%d")

            r = await client.get(
                f"{RECOLLECT_BASE}/places/{place_id}/services/waste/events",
                params={
                    "nomerge": "",
                    "after": after,
                    "before": before,
                    "locale": "en-GB",
                },
            )
            r.raise_for_status()
            data = r.json()

        entries: list[Collection] = []
        for event in data.get("events", []):
            day = event.get("day")
            if not day:
                continue
            try:
                dt = datetime.strptime(day, "%Y-%m-%d").date()
            except ValueError:
                continue
            for flag in event.get("flags", []):
                subject = flag.get("subject", "")
                name = flag.get("name", "")
                icon = ICON_MAP.get(name)
                entries.append(Collection(date=dt, t=subject or name, icon=icon))

        return sorted(entries, key=lambda c: c.date)

    async def _resolve_place(self, client: httpx.AsyncClient) -> str:
        query = self._house_number

        r = await client.get(
            f"{RECOLLECT_BASE}/areas/{AREA}/services/waste/address-suggest",
            params={"q": query, "locale": "en-GB"},
        )
        r.raise_for_status()
        results = r.json()

        if not results:
            raise ValueError(f"No Recollect place found for '{query}'")

        target = self._house_number.lower().strip()
        postcode_lower = self._postcode.lower().strip()
        for item in results:
            name = item.get("name", "").lower()
            if target in name and (not postcode_lower or postcode_lower in name):
                return item["place_id"]

        return results[0]["place_id"]
