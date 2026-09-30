"""Bassetlaw District Council bin collections (ReCollect, EU region).

Flow (plain HTTP JSON, no browser):
  1. GET api.eu.recollect.net/api/areas/BassetlawUK/services/50015/address-suggest
     with q="<house number + street>" (e.g. "10 Albert Road"). Returns parcel
     rows named "10 Albert Road, Retford, DN22 6JB" carrying a place_id UUID.
     The endpoint needs house number + street text: a bare postcode only
     yields a place_qualifier that cannot be expanded into addresses, and
     there is no UPRN lookup, so the caller supplies `address` (+ `postcode`
     to disambiguate between towns).
  2. GET /api/places/{place_id}/services/50015/events for the next ~120 days;
     each event day holds pickup flags (Green Household Waste Bin, etc).

Sibling: port_stirling_council.py (same ReCollect API, different area/service).
Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

from datetime import date, datetime, timedelta

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Bassetlaw District Council"
DESCRIPTION = "Source for bassetlaw.gov.uk bin collections via the ReCollect API."
URL = "https://www.bassetlaw.gov.uk/waste-and-recycling/bin-collections/"
TEST_CASES = {
    "Albert Road, Retford": {"address": "10 Albert Road", "postcode": "DN22 6JB"},
    "Albert Street, Worksop": {"address": "10 Albert Street", "postcode": "S80 1QR"},
}

BASE = "https://api.eu.recollect.net/api"
AREA = "BassetlawUK"
SERVICE = "50015"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

ICON_MAP = {
    "REFUSE": "mdi:trash-can",
    "RECYCLING": "mdi:recycle",
    "GARDEN": "mdi:leaf",
    "GLASS": "mdi:bottle-wine",
    "FOOD": "mdi:food-apple",
}


def _norm(s: str) -> str:
    return " ".join(s.lower().replace(",", " ").split())


class Source:
    def __init__(
        self,
        address: str = "",
        postcode: str = "",
        house_number: str = "",
        uprn: str | int | None = None,
    ):
        # `house_number` is accepted as an alias of `address` (e.g. "10 Albert Road")
        self._address = (address or house_number).strip()
        self._postcode = postcode.strip()

    async def _place_id(self, client: httpx.AsyncClient) -> str:
        if not self._address:
            raise ValueError("address (house number and street) is required")
        r = await client.get(
            f"{BASE}/areas/{AREA}/services/{SERVICE}/address-suggest",
            params={"q": self._address, "locale": "en-GB"},
        )
        r.raise_for_status()
        parcels = [
            x for x in r.json() if x.get("type") == "parcel" and x.get("place_id")
        ]
        if not parcels:
            raise ValueError(f"No Bassetlaw address found for '{self._address}'")
        pc = _norm(self._postcode)
        addr = _norm(self._address)
        for p in parcels:
            name = _norm(p.get("name", ""))
            if (not pc or pc in name) and name.startswith(addr):
                return p["place_id"]
        for p in parcels:
            if not pc or pc in _norm(p.get("name", "")):
                return p["place_id"]
        raise ValueError(
            f"No Bassetlaw address matching '{self._address}' in '{self._postcode}'"
        )

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=30.0, headers=HEADERS
        ) as client:
            place_id = await self._place_id(client)
            today = date.today()
            r = await client.get(
                f"{BASE}/places/{place_id}/services/{SERVICE}/events",
                params={
                    "nomerge": "1",
                    "hide": "reminder_only",
                    "after": today.isoformat(),
                    "before": (today + timedelta(days=120)).isoformat(),
                    "locale": "en-GB",
                },
            )
            r.raise_for_status()
            data = r.json()

        seen: set[tuple[date, str]] = set()
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
                if flag.get("event_type") != "pickup":
                    continue
                label = flag.get("subject") or flag.get("name") or "Unknown"
                if (dt, label) in seen:
                    continue
                seen.add((dt, label))
                entries.append(
                    Collection(date=dt, t=label, icon=ICON_MAP.get(flag.get("name")))
                )
        return sorted(entries, key=lambda c: c.date)
