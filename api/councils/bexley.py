"""Bexley: a per-UPRN iCalendar feed, generated on demand.

Visiting the property page queues the feed; until it's ready the .ics URL
returns a placeholder that doesn't parse, so poll it the way the site does
(hx-trigger="every 2s").
"""

from __future__ import annotations

import asyncio

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    parse_ics,
)

BASE = "https://waste.bexley.gov.uk/waste"
POLLS = 8


class Bexley(Scraper):
    meta = Meta(
        title="London Borough of Bexley",
        url="https://www.bexley.gov.uk",
        lads=("E09000004",),
        cases={
            "Test_001": {"uprn": "200001604426"},
            "Test_002": {"uprn": "100020194783"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        await http.get(f"{BASE}/{uprn}", check=False)  # 503 while the feed is queued
        for _ in range(POLLS):
            r = await http.get(f"{BASE}/{uprn}/calendar.ics", check=False)
            if "BEGIN:VCALENDAR" in r.text:
                return [
                    Collection(event.date, event.summary.replace(" Bin", ""))
                    for event in parse_ics(r.text)
                ]
            await asyncio.sleep(2)
        raise UpstreamError("Bexley's calendar feed never became ready")


SCRAPER = Bexley()
