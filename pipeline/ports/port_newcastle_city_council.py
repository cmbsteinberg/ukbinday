"""Newcastle City Council bin collections (ReCollect, EU region).

The legacy community.newcastle.gov.uk getBinsNew.php endpoint (used by the HACS
source) now answers "The details are not currently available"; the council's
own page embeds a ReCollect widget (area NewcastleUponTyneUK) instead.

Flow (plain HTTP JSON, no browser):
  1. GET api.eu.recollect.net/api/areas/NewcastleUponTyneUK/services/waste/address-suggest
     with q="<house number + street>" (e.g. "1 Grange Road"). Returns parcel
     rows named "1 Grange Road, Newcastle upon Tyne, NE3 5LA" carrying a place_id UUID.
     The endpoint needs house number + street text: a bare postcode only
     yields a place_qualifier that cannot be expanded into addresses, and
     there is no UPRN lookup, so the caller supplies `address` (+ `postcode`
     to disambiguate between towns).
  2. GET /api/places/{place_id}/services/waste/events for the next ~120 days;
     each event day holds pickup flags (General Waste, Recycling with Plastic Bags and Wrapping, etc).

Sibling: port_bassetlaw_district_council.py / port_stirling_council.py.
Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

from datetime import date, datetime, timedelta

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Newcastle City Council"
DESCRIPTION = "Source for newcastle.gov.uk bin collections via the ReCollect API."
URL = "https://new.newcastle.gov.uk/recycling-waste/check-your-bin-collection-day"
TEST_CASES = {
    "Grange Road": {"address": "1 Grange Road", "postcode": "NE3 5LA"},
    "Westerhope": {
        "address": "1 Westerhope Homes Hillhead Road",
        "postcode": "NE5 1NJ",
    },
}

BASE = "https://api.eu.recollect.net/api"
AREA = "NewcastleUponTyneUK"
SERVICE = "waste"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

ICON_MAP = {
    "GeneralWaste": "mdi:trash-can",
    "RecyclingwithFlex": "mdi:recycle",
    "Recycling": "mdi:recycle",
    "Garden": "mdi:leaf",
    "GardenWaste": "mdi:leaf",
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
        # `house_number` is accepted as an alias of `address` (e.g. "1 Grange Road")
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
            raise ValueError(f"No Newcastle address found for '{self._address}'")
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
            f"No Newcastle address matching '{self._address}' in '{self._postcode}'"
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
