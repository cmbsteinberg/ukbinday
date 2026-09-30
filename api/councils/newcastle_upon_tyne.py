"""Newcastle City Council: find a ReCollect parcel by address, then fetch its waste events."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
)

_BASE = "https://api.eu.recollect.net/api"
_AREA = "NewcastleUponTyneUK"
_SERVICE = "waste"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def _norm(text: str) -> str:
    return " ".join(text.lower().replace(",", " ").split())


def _parcel_name(parcel: dict[str, Any]) -> str:
    name = parcel.get("name", "")
    return name if isinstance(name, str) else ""


class NewcastleUponTyne(Scraper):
    meta = Meta(
        title="Newcastle City Council",
        url="https://new.newcastle.gov.uk/recycling-waste/check-your-bin-collection-day",
        lads=("E08000021",),
        cases={
            "Grange Road": {
                "house_number": "1",
                "street": "Grange Road",
                "postcode": "NE3 5LA",
            },
            "Westerhope": {
                "house_number": "1",
                "street": "Westerhope Homes Hillhead Road",
                "postcode": "NE5 1NJ",
            },
        },
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        address_text = address.first_line
        if not address_text:
            raise InputError("Newcastle needs a house number and street")

        response = await http.get(
            f"{_BASE}/areas/{_AREA}/services/{_SERVICE}/address-suggest",
            params={"q": address_text, "locale": "en-GB"},
            timeout=30.0,
        )
        parcels = [
            parcel
            for parcel in response.json()
            if parcel.get("type") == "parcel" and parcel.get("place_id")
        ]
        if not parcels:
            raise AddressNotFound(f"No Newcastle address found for {address_text!r}")

        if address.postcode:
            postcode = _norm(address.postcode)
            parcels = [
                parcel for parcel in parcels if postcode in _norm(_parcel_name(parcel))
            ]

        parcel = match_address(address, parcels, text=_parcel_name)
        place_id = parcel["place_id"]

        today = date.today()
        response = await http.get(
            f"{_BASE}/places/{place_id}/services/{_SERVICE}/events",
            params={
                "nomerge": "1",
                "hide": "reminder_only",
                "after": today.isoformat(),
                "before": (today + timedelta(days=120)).isoformat(),
                "locale": "en-GB",
            },
            timeout=30.0,
        )
        data = response.json()

        collections: list[Collection] = []
        for event in data.get("events", []):
            day = event.get("day")
            if not day:
                continue
            try:
                collection_date = datetime.strptime(day, "%Y-%m-%d").date()
            except ValueError:
                continue
            for flag in event.get("flags", []):
                if flag.get("event_type") != "pickup":
                    continue
                label = flag.get("subject") or flag.get("name") or "Unknown"
                collections.append(Collection(collection_date, label))
        return collections


SCRAPER = NewcastleUponTyne()
