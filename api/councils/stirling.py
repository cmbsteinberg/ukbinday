"""Stirling: resolve an address through Recollect, then fetch its waste events."""

from __future__ import annotations

from datetime import datetime, timedelta

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

_RECOLLECT_BASE = "https://api.eu.recollect.net/api"
_AREA = "StirlingUK"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


class Stirling(Scraper):
    meta = Meta(
        title="Stirling Council",
        url="https://www.stirling.gov.uk",
        lads=("S12000030",),
        cases={
            "Test_001": {
                "postcode": "FK9 4QA",
                "house_number": "5",
                "street": "Sunnylaw Road",
            },
        },
    )
    requires = frozenset()
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        query = address.first_line
        if query is None:
            raise InputError("Stirling needs an address")

        r = await http.get(
            f"{_RECOLLECT_BASE}/areas/{_AREA}/services/waste/address-suggest",
            params={"q": query, "locale": "en-GB"},
            timeout=30.0,
        )
        results = r.json()

        if not results:
            raise AddressNotFound(f"No Recollect place found for {query!r}")

        try:
            place = match_address(
                address,
                results,
                text=lambda item: item.get("name", ""),
                uprn=lambda item: item.get("uprn"),
            )
        except AddressNotFound:
            place = results[0]
        place_id = place["place_id"]

        now = datetime.now()
        after = now.strftime("%Y-%m-%d")
        before = (now + timedelta(days=90)).strftime("%Y-%m-%d")

        r = await http.get(
            f"{_RECOLLECT_BASE}/places/{place_id}/services/waste/events",
            params={
                "nomerge": "",
                "after": after,
                "before": before,
                "locale": "en-GB",
            },
            timeout=30.0,
        )
        data = r.json()

        entries: list[Collection] = []
        for event in data.get("events", []):
            day = event.get("day")
            if not day:
                continue
            try:
                collection_date = datetime.strptime(day, "%Y-%m-%d").date()
            except ValueError:
                continue
            for flag in event.get("flags", []):
                subject = flag.get("subject", "")
                name = flag.get("name", "")
                entries.append(Collection(collection_date, subject or name))

        return entries


SCRAPER = Stirling()
