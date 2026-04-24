from datetime import datetime

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Mid Ulster District Council"
DESCRIPTION = "Source for midulstercouncil.org waste collection."
URL = "https://www.midulstercouncil.org"
TEST_CASES = {
    "Test_001": {"uprn": "185649901", "postcode": "BT71 5HY"},
}

API_BASE = "https://midulsterbincalendar.azurewebsites.net/api"
HEADERS = {"User-Agent": "Mozilla/5.0"}

ICON_MAP = {
    "Blue": "mdi:recycle",
    "Black": "mdi:trash-can",
    "Brown": "mdi:leaf",
    "Green": "mdi:recycle",
}


class Source:
    def __init__(self, uprn: str | int | None = None, postcode: str | None = None, house_number: str | None = None):
        self._uprn = str(uprn) if uprn else None
        self._postcode = postcode or ""
        self._address = house_number or ""

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as s:
            uprn = self._uprn

            if not uprn and self._postcode:
                r = await s.get(
                    f"{API_BASE}/addresses/{self._postcode}",
                    headers=HEADERS,
                )
                r.raise_for_status()
                data = r.json()
                for addr in data.get("addresses", []):
                    if self._address and self._address.upper() in addr.get("addressText", "").upper():
                        uprn = addr["uprn"]
                        break
                if not uprn and data.get("addresses"):
                    uprn = data["addresses"][0]["uprn"]

            if not uprn:
                return []

            r = await s.get(
                f"{API_BASE}/collectiondates/{uprn}",
                headers=HEADERS,
            )
            r.raise_for_status()
            data = r.json()

        entries = []
        for week_key in ("lastWeek", "thisWeek", "nextWeek"):
            week = data.get(week_key)
            if not week or not week.get("date"):
                continue
            try:
                dt = datetime.fromisoformat(week["date"]).date()
            except (ValueError, TypeError):
                continue
            for bin_info in week.get("bins", []):
                colour = bin_info.get("colour", "")
                name = bin_info.get("name", "")
                capacity = bin_info.get("capacity", "")
                bin_type = f"{name} ({colour})" if colour else name
                if capacity:
                    bin_type = f"{bin_type} {capacity}"
                icon = ICON_MAP.get(colour)
                entries.append(Collection(date=dt, t=bin_type, icon=icon))

        return sorted(entries, key=lambda c: c.date)
