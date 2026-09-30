"""East Ayrshire: resolve an address through ReCollect, then fetch its waste events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

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

API_BASE = "https://api.eu.recollect.net/api"
AREA_URL = f"{API_BASE}/areas/EastAyrshireUK/services/waste"


def _norm(text: str) -> str:
    return " ".join(text.lower().replace(",", " ").split())


def _candidate_name(candidate: Mapping[str, object]) -> str:
    name = candidate.get("name")
    return name if isinstance(name, str) else ""


class EastAyrshire(Scraper):
    meta = Meta(
        title="East Ayrshire Council",
        url="https://www.east-ayrshire.gov.uk/",
        lads=("S12000008",),
        cases={
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
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        if address.house_number and address.street:
            query = f"{address.house_number} {address.street}"
        elif address.label:
            query = address.label.split(",")[0]
        else:
            raise InputError("East Ayrshire needs a house number and street, or an address")

        r = await http.get(
            f"{AREA_URL}/address-suggest",
            params={"q": query, "locale": "en-GB"},
            timeout=30,
        )
        parcels = [
            parcel
            for parcel in r.json()
            if isinstance(parcel, dict)
            and parcel.get("type") == "parcel"
            and parcel.get("place_id")
        ]

        if address.postcode:
            postcode = _norm(address.postcode)
            parcels = [
                parcel for parcel in parcels
                if _norm(_candidate_name(parcel)).endswith(postcode)
            ]

        if not parcels:
            raise AddressNotFound(f"Address not found: {query} {address.postcode or ''}")

        selected = match_address(address, parcels, text=_candidate_name)
        place_id = selected["place_id"]

        r = await http.get(
            f"{API_BASE}/places/{place_id}/services/waste/events",
            params={
                "hide": "reminder_only",
                "after": (date.today() - timedelta(days=30)).isoformat(),
                "before": (date.today() + timedelta(days=365)).isoformat(),
                "locale": "en-GB",
            },
            timeout=30,
        )

        collections: list[Collection] = []
        for event in r.json().get("events", []):
            collection_date = date.fromisoformat(event["day"])
            for flag in event.get("flags", []):
                if flag.get("event_type") != "pickup":
                    continue
                waste_type = flag.get("subject") or flag.get("name")
                if not waste_type:
                    continue
                collections.append(Collection(collection_date, waste_type))
        return collections


SCRAPER = EastAyrshire()
