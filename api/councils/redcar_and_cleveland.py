"""Redcar and Cleveland: search ReCollect by postcode, then fetch the property's next 30 days of events."""

from __future__ import annotations

import time
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

_SUGGEST_URL = "https://api.eu.recollect.net/api/areas/RedcarandClevelandUK/services/50006/address-suggest"
_EVENTS_URL = "https://api.eu.recollect.net/api/places/{place_id}/services/50006/events"


class RedcarAndCleveland(Scraper):
    meta = Meta(
        title="Redcar and Cleveland",
        url="https://www.redcar-cleveland.gov.uk",
        lads=("E06000003",),
        cases={},
    )
    requires = frozenset({"postcode", "house_number"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        suggestions = await http.get(
            _SUGGEST_URL,
            params={
                "q": address.need("postcode"),
                "locale": "en-GB",
                "_": str(int(time.time() * 1000)),
            },
        )
        addresses = suggestions.json()

        try:
            selected = match_address(
                address,
                addresses,
                text=lambda item: item.get("name", ""),
            )
            place_id = selected["place_id"]
        except AddressNotFound:
            place_id = addresses[1]["place_id"] if addresses[1] else None

        after = datetime.today()
        before = after + timedelta(days=30)

        response = await http.get(
            _EVENTS_URL.format(place_id=place_id),
            params={
                "nomerge": 1,
                "hide": "reminder_only",
                "after": after.strftime("%Y-%m-%d"),
                "before": before.strftime("%Y-%m-%d"),
                "locale": "en-GB",
                "include_message": "email",
                "_": str(int(time.time() * 1000)),
            },
        )

        collections = []
        for event in response.json()["events"]:
            for flag in event.get("flags", []):
                try:
                    day = datetime.strptime(event["end_day"], "%Y-%m-%d").date()
                except ValueError:
                    continue
                collections.append(Collection(day, flag["name"]))

        return collections


SCRAPER = RedcarAndCleveland()
