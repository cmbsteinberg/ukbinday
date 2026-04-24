from datetime import datetime, timedelta

import httpx
from icalendar import Calendar

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Dumfries and Galloway Council"
DESCRIPTION = "Source for dumfriesandgalloway.gov.uk waste collection."
URL = "https://www.dumfriesandgalloway.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "137034556"},
}

ICS_URL = "https://www.dumfriesandgalloway.gov.uk/bins-recycling/waste-collection-schedule/download/{uprn}"

ICON_MAP = {
    "RECYCLING": "mdi:recycle",
    "REFUSE": "mdi:trash-can",
    "GARDEN": "mdi:leaf",
    "FOOD": "mdi:food-apple",
    "GLASS": "mdi:glass-fragile",
}


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = str(uprn)

    async def fetch(self) -> list[Collection]:
        url = ICS_URL.format(uprn=self._uprn)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()

        cal = Calendar.from_ical(r.content)
        now = datetime.now()
        future = now + timedelta(days=60)
        entries = []

        for event in cal.walk("VEVENT"):
            summary = event.get("SUMMARY")
            dtstart = event.get("DTSTART")
            if not summary or not dtstart:
                continue
            dt = dtstart.dt
            if hasattr(dt, "date"):
                dt = dt.date()
            if dt < now.date() or dt > future.date():
                continue
            for collection in str(summary).split(","):
                name = collection.strip()
                icon = ICON_MAP.get(name.upper().split()[0], None) if name else None
                entries.append(Collection(date=dt, t=name, icon=icon))

        return sorted(entries, key=lambda c: c.date)
