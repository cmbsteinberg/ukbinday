"""Caerphilly: postcode and house number resolve a ReCollect place, then pickup events provide collection dates."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    match_address,
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
}
_AREA = "CaerphillyCountyUK"
_SERVICE = "50008"
_SUGGEST_URL = f"https://api.eu.recollect.net/api/areas/{_AREA}/services/{_SERVICE}/address-suggest"
_EVENTS_URL_TEMPLATE = (
    f"https://api.eu.recollect.net/api/places/{{place_id}}/services/{_SERVICE}/events"
)
_CALENDAR_URL = (
    f"https://api.eu.recollect.net/api/areas/{_AREA}/services/{_SERVICE}"
    "/pages/en-GB/place_calendar.json"
)
_WIDGET_CONFIG = {
    "area": _AREA,
    "name": "calendar",
    "locale": "en-GB",
    "base": "https://api.eu.recollect.net",
    "place_cookie": f"rCw-{_AREA}-waste",
    "client_cookie": f"rCc-{_AREA}",
    "cookie_expires": 14,
    "third_party_cookie_enabled": 1,
    "place_not_found_in_guest": 0,
    "is_guest_service": 0,
}


async def _resolve_place_id(address: Address, http: Http) -> str:
    postcode = address.need("postcode")

    response = await http.get(
        _SUGGEST_URL,
        params={"q": postcode, "locale": "en-GB"},
        timeout=30,
    )
    results = response.json()

    parcels = [
        result
        for result in results
        if result.get("type") == "parcel" and result.get("place_id")
    ]
    if parcels:
        return match_address(address, parcels, text=lambda parcel: parcel.get("name", ""))[
            "place_id"
        ]

    qualifiers = [result for result in results if result.get("type") == "place_qualifier"]
    if not qualifiers:
        raise AddressNotFound(f"No results for postcode: {postcode}")

    qualifier_id = qualifiers[0]["qualifier_id"]
    response = await http.get(
        _CALENDAR_URL,
        headers={"X-Recollect-Place": f"qualifier.{qualifier_id}:{_SERVICE}"},
        params={"widget_config": json.dumps(_WIDGET_CONFIG)},
        timeout=30,
        check=False,
    )
    calendar_data = response.json()

    addresses = []
    for section in calendar_data.get("sections", []):
        for row in section.get("rows", []):
            if row.get("action") == "SET_PLACE" and row.get("place_id"):
                place_id = row["place_id"]
                addresses.append(
                    {
                        "name": row.get("label", ""),
                        "place_id": place_id.split(":")[0] if ":" in place_id else place_id,
                    }
                )

    if not addresses:
        raise AddressNotFound(
            f"No addresses found for postcode {postcode} (qualifier {qualifier_id})"
        )

    # Keep the resolved house number required by the council's address lookup.
    address.need("house_number")
    return match_address(address, addresses, text=lambda candidate: candidate["name"])[
        "place_id"
    ]


class Caerphilly(Scraper):
    meta = Meta(
        title="Caerphilly County Borough",
        url="https://www.caerphilly.gov.uk",
        lads=("W06000018",),
        cases={},
    )
    requires = frozenset({"postcode", "house_number"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        place_id = await _resolve_place_id(address, http)

        now = datetime.now()
        params = {
            "nomerge": "1",
            "hide": "reminder_only",
            "after": now.strftime("%Y-%m-%d"),
            "before": (now + timedelta(days=60)).strftime("%Y-%m-%d"),
            "locale": "en-GB",
        }
        response = await http.get(
            _EVENTS_URL_TEMPLATE.format(place_id=place_id),
            params=params,
            timeout=60,
        )
        events_data = response.json()

        collections = []
        for event in events_data.get("events", []):
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
                bin_type = flag.get("subject") or flag.get("name", "Unknown")
                collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = Caerphilly()
