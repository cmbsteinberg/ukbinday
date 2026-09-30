"""Enfield: resolve a full address to a UPRN, then fetch its collection schedule."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
    match_address,
)

_URL = "https://www.enfield.gov.uk/services/rubbish-and-recycling/find-my-collection-day"
_LOOKUP_URL = "https://www.enfield.gov.uk/_design/integrations/ordnance-survey/places-v2"
_SCHEDULE_URL = "https://www.enfield.gov.uk/_design/integrations/bartec/find-my-collection/rest/schedule"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": _URL,
}

_TYPE_KEYWORDS = {
    "FOOD": "Food Waste",
    "RECYCL": "Recycling",
    "RESIDUAL": "General Waste",
    "REFUSE": "General Waste",
    "GARDEN": "Garden Waste",
}


def _get_nested_text(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    if isinstance(value, dict):
        return value.get("_text")
    if isinstance(value, str):
        return value
    return None


def _normalize_waste_type(job_name: str) -> str:
    upper_name = job_name.upper()
    for keyword, label in _TYPE_KEYWORDS.items():
        if keyword in upper_name:
            return label
    return re.sub(r"^EMPTY BIN\s+", "", job_name, flags=re.IGNORECASE).strip()


class Enfield(Scraper):
    meta = Meta(
        title="Enfield Council",
        url=_URL,
        lads=("E09000010",),
        cases={
            "uprn": {"uprn": "207102166"},
            "address": {
                "address": "127 Palmerston Rd, London N22 8QX",
                "house_number": "127",
                "street": "Palmerston Rd",
                "postcode": "N22 8QX",
            },
        },
    )
    requires = frozenset()
    headers = _HEADERS
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        await http.get(_URL, timeout=30)

        uprn = address.uprn
        if uprn is None:
            query = address.label or address.first_line
            if query is None:
                raise InputError("Provide either a UPRN or a full Enfield address.")
            uprn = await self._resolve_uprn(query, address, http)

        response = await http.get(
            _SCHEDULE_URL,
            params={"uprn": uprn},
            timeout=30,
        )
        data = response.json()

        if not data:
            raise AddressNotFound(f"No collection data was returned for UPRN {uprn}.")

        collections = []
        for item in data:
            scheduled_start = _get_nested_text(item, "ScheduledStart")
            job_name = _get_nested_text(item, "JobName") or _get_nested_text(
                item, "Description"
            )
            if not scheduled_start or not job_name:
                continue

            collections.append(
                Collection(
                    date=datetime.strptime(scheduled_start, "%Y-%m-%dT%H:%M:%S").date(),
                    type=_normalize_waste_type(job_name),
                )
            )

        if not collections:
            raise AddressNotFound(f"No collection data was returned for UPRN {uprn}.")

        return collections

    async def _resolve_uprn(self, query: str, address: Address, http: Http) -> str:
        response = await http.get(
            _LOOKUP_URL,
            params={"query": query},
            timeout=30,
        )
        results = response.json().get("results", [])
        candidates = [
            lpi
            for result in results
            if isinstance((lpi := result.get("LPI")), dict)
        ]
        if not candidates:
            raise AddressNotFound(f"No Enfield addresses matched {query!r}.")

        match = match_address(
            address,
            candidates,
            text=lambda lpi: str(lpi.get("ADDRESS") or ""),
            uprn=lambda lpi: lpi.get("UPRN"),
        )
        uprn = match.get("UPRN")
        if not uprn:
            raise AddressNotFound(f"No UPRN was returned for {query!r}.")
        return str(uprn)


SCRAPER = Enfield()
