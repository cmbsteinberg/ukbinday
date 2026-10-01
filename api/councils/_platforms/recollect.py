"""ReCollect waste calendars (`api.eu.recollect.net`), used by Newcastle, Stirling...

Every area runs the same API:

1. `GET areas/<area>/services/<service>/address-suggest?q=...` answers with
   `parcel` rows (an address and its `place_id`) and, for a postcode query,
   `place_qualifier` rows. A qualifier is expanded into its addresses through
   the area's `place_calendar.json` page, keyed by an `X-Recollect-Place` header.
2. `GET places/<place_id>/services/<service>/events` lists dated events whose
   `pickup` flags are the bins collected that day.

We search by the address's first line, which most areas answer with the one
parcel, and fall back to the postcode. What differs per council is the area,
the service and how far ahead to look, in `ReCollectConfig`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Platform,
    match_address,
    normalise_text,
)

_BASE = "https://api.eu.recollect.net/api"
_TIMEOUT = 30


@dataclass(frozen=True, slots=True, kw_only=True)
class ReCollectConfig:
    area: str
    """"NewcastleUponTyneUK"."""
    service: str
    """The service id ("50008") or name ("waste") the council's widget uses."""
    days: int = 60
    """How far ahead to list collections."""
    days_back: int = 0
    """How far back to list them."""


@dataclass(frozen=True, slots=True)
class _Place:
    name: str
    place_id: str


def _parcels(results: list[dict[str, Any]], postcode: str | None) -> list[_Place]:
    """The parcel rows, restricted to the postcode when we have one."""
    places = [
        _Place(str(row.get("name") or ""), str(row["place_id"]))
        for row in results
        if row.get("type") == "parcel" and row.get("place_id")
    ]
    return _in_postcode(places, postcode)


def _in_postcode(places: list[_Place], postcode: str | None) -> list[_Place]:
    if not postcode:
        return places
    wanted = normalise_text(postcode)
    return [p for p in places if wanted in normalise_text(p.name)]


class ReCollect(Platform[ReCollectConfig]):
    requires = frozenset()  # an address's first line, or a postcode plus house number
    headers: Mapping[str, str] = MappingProxyType(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }
    )

    async def _suggest(self, http: Http, query: str) -> list[dict[str, Any]]:
        cfg = self.config
        r = await http.get(
            f"{_BASE}/areas/{cfg.area}/services/{cfg.service}/address-suggest",
            params={"q": query, "locale": "en-GB"},
            timeout=_TIMEOUT,
        )
        data = r.json()
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    async def _expand(self, http: Http, qualifier: Mapping[str, Any]) -> list[_Place]:
        """The addresses behind a `place_qualifier` (usually a postcode)."""
        area = self.config.area
        service = qualifier.get("service_id") or self.config.service
        r = await http.get(
            f"{_BASE}/areas/{area}/services/{service}/pages/en-GB/place_calendar.json",
            headers={"X-Recollect-Place": f"qualifier.{qualifier['qualifier_id']}:{service}"},
            params={"widget_config": json.dumps({"area": area, "name": "calendar", "locale": "en-GB"})},
            timeout=_TIMEOUT,
            check=False,  # answers 401 alongside a usable address list
        )
        return [
            _Place(str(row.get("label") or ""), str(row["place_id"]).split(":")[0])
            for section in r.json().get("sections", [])
            for row in section.get("rows", [])
            if row.get("action") == "SET_PLACE" and row.get("place_id")
        ]

    async def _places(self, address: Address, http: Http) -> list[_Place]:
        if first_line := address.first_line:
            if places := _parcels(await self._suggest(http, first_line), address.postcode):
                return places
        if address.postcode:
            results = await self._suggest(http, address.postcode)
            places = _parcels(results, address.postcode)
            if not places:
                for row in results:
                    if row.get("type") == "place_qualifier" and row.get("qualifier_id"):
                        places += _in_postcode(await self._expand(http, row), address.postcode)
            if places:
                return places
        elif not first_line:
            raise InputError("Provide a house number and street, or a postcode")
        raise AddressNotFound(f"No address on {self.config.area} for {first_line or address.postcode!r}")

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        place = match_address(address, await self._places(address, http), text=lambda p: p.name)

        cfg = self.config
        today = date.today()
        r = await http.get(
            f"{_BASE}/places/{place.place_id}/services/{cfg.service}/events",
            params={
                "nomerge": "1",
                "hide": "reminder_only",
                "after": (today - timedelta(days=cfg.days_back)).isoformat(),
                "before": (today + timedelta(days=cfg.days)).isoformat(),
                "locale": "en-GB",
            },
            timeout=_TIMEOUT,
        )

        collections: list[Collection] = []
        for event in r.json().get("events", []):
            try:
                day = date.fromisoformat(event.get("day") or "")
            except ValueError:
                continue
            for flag in event.get("flags", []):
                if flag.get("event_type") != "pickup":
                    continue
                if bin_type := flag.get("subject") or flag.get("name"):
                    collections.append(Collection(day, bin_type))
        return collections
