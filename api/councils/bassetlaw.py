"""Bassetlaw: find a property through ReCollect's address suggestions, then fetch its collection events."""

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
)

BASE = "https://api.eu.recollect.net/api"
AREA = "BassetlawUK"
SERVICE = "50015"


def _norm(value: str) -> str:
    return " ".join(value.lower().replace(",", " ").split())


def _parcel_name(parcel: dict[str, Any]) -> str:
    return parcel.get("name", "")


class Bassetlaw(Scraper):
    meta = Meta(
        title="Bassetlaw District Council",
        url="https://www.bassetlaw.gov.uk/waste-and-recycling/bin-collections/",
        lads=("E07000171",),
        cases={
            "Albert Road, Retford": {
                "postcode": "DN22 6JB",
                "house_number": "10",
                "street": "Albert Road",
            },
            "Albert Street, Worksop": {
                "postcode": "S80 1QR",
                "house_number": "10",
                "street": "Albert Street",
            },
        },
    )
    requires = frozenset()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        search_text = address.first_line
        if not search_text:
            raise InputError("Bassetlaw needs a house number and street")

        r = await http.get(
            f"{BASE}/areas/{AREA}/services/{SERVICE}/address-suggest",
            params={"q": search_text, "locale": "en-GB"},
            timeout=30.0,
        )
        parcels = [
            parcel
            for parcel in r.json()
            if parcel.get("type") == "parcel" and parcel.get("place_id")
        ]
        if not parcels:
            raise AddressNotFound(f"No Bassetlaw address found for '{search_text}'")

        postcode = _norm(address.postcode or "")
        address_text = _norm(search_text)
        candidates = [
            parcel
            for parcel in parcels
            if not postcode or postcode in _norm(_parcel_name(parcel))
        ]
        if not candidates:
            raise AddressNotFound(
                f"No Bassetlaw address matching '{search_text}' in '{address.postcode or ''}'"
            )

        try:
            selected = next(
                parcel
                for parcel in candidates
                if _norm(_parcel_name(parcel)).startswith(address_text)
            )
        except StopIteration:
            try:
                selected = __import__(
                    "api.councils._base", fromlist=["match_address"]
                ).match_address(address, candidates, text=_parcel_name)
            except AddressNotFound:
                selected = candidates[0]

        today = date.today()
        r = await http.get(
            f"{BASE}/places/{selected['place_id']}/services/{SERVICE}/events",
            params={
                "nomerge": "1",
                "hide": "reminder_only",
                "after": today.isoformat(),
                "before": (today + timedelta(days=120)).isoformat(),
                "locale": "en-GB",
            },
            timeout=30.0,
        )
        data = r.json()

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


SCRAPER = Bassetlaw()
