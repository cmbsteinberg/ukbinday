"""Peterborough: fetches the collection iCalendar feed using the postcode and UPRN."""

from __future__ import annotations

from api.councils._base import Address, Collection, Http, Meta, Scraper, parse_ics

_COLLECTION_URL = "https://report.peterborough.gov.uk/waste/{postcode}:{uprn}/calendar.ics"


class Peterborough(Scraper):
    meta = Meta(
        title="Peterborough City Council",
        url="https://peterborough.gov.uk",
        lads=("E06000031",),
        cases={"houseUprn": {"postcode": "PE57AX", "uprn": "100090214774"}},
    )
    requires = frozenset({"postcode", "uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        url = _COLLECTION_URL.format(
            postcode=address.need("postcode"),
            uprn=address.need("uprn"),
        )
        r = await http.get(url, timeout=10)
        return [Collection(event.date, event.summary) for event in parse_ics(r.text)]


SCRAPER = Peterborough()
