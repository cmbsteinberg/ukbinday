from datetime import date, timedelta

import httpx

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]

TITLE = "East Ayrshire Council"
DESCRIPTION = "Source for east-ayrshire.gov.uk services for East Ayrshire"
URL = "https://www.east-ayrshire.gov.uk/"

TEST_CASES = {
    "39 Heathfield Road, Auchinleck": {
        "house_number": "39",
        "street": "Heathfield Road",
        "postcode": "KA18 2JB",
    },
    "6 Sim Gardens, Darvel": {
        "house_number": "6",
        "street": "Sim Gardens",
        "postcode": "KA17 0LD",
    },
}

# East Ayrshire's "Check your bin collection day" page embeds Routeware's
# ReCollect widget (area "EastAyrshireUK"); the old UPRN calendar page is gone.
API_BASE = "https://api.eu.recollect.net/api"
AREA_URL = f"{API_BASE}/areas/EastAyrshireUK/services/waste"

ICON_MAP = {
    "general waste": Icons.GENERAL_WASTE,
    "garden": Icons.GARDEN,
    "food": Icons.BIO_KITCHEN,
    "glass": Icons.GLASS,
    "paper": Icons.PAPER,
    "plastic": Icons.RECYCLING,
    "recycling": Icons.RECYCLING,
}


def _icon(*names: str | None):
    text = " ".join(n.lower() for n in names if n)
    for key, icon in ICON_MAP.items():
        if key in text:
            return icon
    return None


def _norm(s: str) -> str:
    return " ".join(s.lower().replace(",", " ").split())


class Source:
    def __init__(
        self,
        postcode: str | None = None,
        house_number: str | None = None,
        street: str | None = None,
        address: str | None = None,
        uprn: str | int | None = None,
    ):
        self._postcode = postcode.strip() if postcode else None
        self._house_number = house_number.strip() if house_number else None
        self._street = street.strip() if street else None
        self._address = address.strip() if address else None
        if not (self._house_number and self._street) and not self._address:
            raise ValueError("house_number and street (or address) required")

    def _query(self) -> str:
        if self._house_number and self._street:
            return f"{self._house_number} {self._street}"
        return self._address.split(",")[0]

    async def _resolve_place_id(self, client: httpx.AsyncClient) -> str:
        r = await client.get(
            f"{AREA_URL}/address-suggest",
            params={"q": self._query(), "locale": "en-GB"},
            timeout=30,
        )
        r.raise_for_status()
        parcels = [s for s in r.json() if s.get("type") == "parcel" and s.get("place_id")]

        if self._postcode:
            pc = _norm(self._postcode)
            parcels = [p for p in parcels if _norm(p["name"]).endswith(pc)]

        if not parcels:
            raise ValueError(f"Address not found: {self._query()} {self._postcode or ''}")

        # Prefer an exact "<number> <street>" match over prefix matches ("3" vs "39").
        q = _norm(self._query())
        exact = [p for p in parcels if _norm(p["name"]).startswith(q + " ")]
        if len(exact) == 1:
            return exact[0]["place_id"]
        if len(parcels) == 1:
            return parcels[0]["place_id"]
        raise ValueError(
            "Address is ambiguous: " + "; ".join(p["name"] for p in (exact or parcels)[:5])
        )

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            place_id = await self._resolve_place_id(client)
            r = await client.get(
                f"{API_BASE}/places/{place_id}/services/waste/events",
                params={
                    "hide": "reminder_only",
                    "after": (date.today() - timedelta(days=30)).isoformat(),
                    "before": (date.today() + timedelta(days=365)).isoformat(),
                    "locale": "en-GB",
                },
                timeout=30,
            )
            r.raise_for_status()
            events = r.json().get("events", [])

        entries: list[Collection] = []
        for event in events:
            collection_date = date.fromisoformat(event["day"])
            for flag in event.get("flags", []):
                if flag.get("event_type") != "pickup":
                    continue
                waste_type = flag.get("subject") or flag.get("name")
                if not waste_type:
                    continue
                entries.append(
                    Collection(
                        date=collection_date,
                        t=waste_type,
                        icon=_icon(flag.get("name"), waste_type),
                    )
                )
        return entries
