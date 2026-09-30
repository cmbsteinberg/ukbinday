"""Doncaster: looks up a UPRN's collections from the council's calendar API."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper

_BASE = "https://www.doncaster.gov.uk/Compass/PremiseDetail/GetCollectionsForCalendar"
_DATE_PATTERN = re.compile(r"\(([0-9]{10})")


class Doncaster(Scraper):
    meta = Meta(
        title="City of Doncaster Council",
        url="https://doncaster.gov.uk",
        lads=("E08000017",),
        cases={
            "Test_001": {"uprn": "100050701118"},
            "Test_002": {"uprn": "100050753396"},
            "Test_003": {"uprn": "100050699118"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)

        # Query needs start and end epoch dates.
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = (today - timedelta(days=365)).strftime("%s")
        end = (today + timedelta(days=365)).strftime("%s")
        url = f"{_BASE}?UPRN={uprn}&Start={start}&End={end}"
        r = await http.get(url)
        data = r.json()

        collections = []
        for entry in data["slots"]:
            waste_type = entry["title"]
            waste_date = entry["end"]
            epoch = _DATE_PATTERN.findall(waste_date)
            day = datetime.fromtimestamp(int(epoch[0])).date()
            collections.append(Collection(day, waste_type))

        return collections


SCRAPER = Doncaster()
