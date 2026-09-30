"""Dumfries and Galloway: fetches a UPRN-specific iCalendar feed and returns collections for the next 60 days."""

from __future__ import annotations

from datetime import date, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper, parse_ics

_ICS_URL = "https://www.dumfriesandgalloway.gov.uk/bins-recycling/waste-collection-schedule/download/{uprn}"


class DumfriesAndGalloway(Scraper):
    meta = Meta(
        title="Dumfries and Galloway Council",
        url="https://www.dumfriesandgalloway.gov.uk",
        lads=("S12000006",),
        cases={"Test_001": {"uprn": "137034556"}},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_ICS_URL.format(uprn=address.need("uprn")))
        today = date.today()
        last_day = today + timedelta(days=60)

        collections = []
        for event in parse_ics(r.text):
            if event.date < today or event.date > last_day:
                continue
            for name in event.summary.split(","):
                name = name.strip()
                if name:
                    collections.append(Collection(event.date, name))
        return collections


SCRAPER = DumfriesAndGalloway()
