from datetime import datetime, timedelta
from typing import Any
import httpx
from icalevents.icalevents import events

from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.compat.ukbcd.common import date_format


class CouncilClass(AbstractGetBinDataClass):
    async def parse_data(self, page: str, **kwargs: Any) -> dict:
        ics_url: str = kwargs.get("url")

        if not ics_url:
            raise ValueError("Missing required argument: url")

        # Get events within the next 90 days
        now = datetime.now()
        future = now + timedelta(days=60)

        try:
            upcoming_events = events(ics_url, start=now, end=future)
        except Exception as e:
            raise ValueError(f"Error parsing ICS feed: {e}")

        bindata = {"bins": []}

        for event in sorted(upcoming_events, key=lambda e: e.start):
            if not event.summary or not event.start:
                continue

            bindata["bins"].append(
                {
                    "type": event.summary,
                    "collectionDate": event.start.date().strftime(date_format),
                }
            )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Google Calendar (Public)"
URL = "https://calendar.google.com/calendar/ical/0d775884b4db6a7bae5204f06dae113c1a36e505b25991ebc27c6bd42edf5b5e%40group.calendar.google.com/public/basic.ics"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None):
        self.uprn = uprn
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn

        data = await self._scraper.parse_data("", **kwargs)

        entries = []
        if isinstance(data, dict) and "bins" in data:
            for item in data["bins"]:
                bin_type = item.get("type")
                date_str = item.get("collectionDate")
                if not bin_type or not date_str:
                    continue
                try:
                    if "-" in date_str:
                        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                    elif "/" in date_str:
                        dt = datetime.strptime(date_str, "%d/%m/%Y").date()
                    else:
                        continue
                    entries.append(Collection(date=dt, t=bin_type, icon=None))
                except ValueError:
                    continue
        return entries
