from icalevents.icalevents import events

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


# import the wonderful Beautiful Soup and the URL grabber
class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page: str, **kwargs) -> dict:

        user_uprn = kwargs.get("uprn")
        user_uprn = str(user_uprn).zfill(12)
        check_uprn(user_uprn)
        bindata = {"bins": []}

        ics_url = f"https://www.hinckley-bosworth.gov.uk/bin-collection-feed?round={user_uprn}"

        # Get events from ICS file within the next 365 days
        now = datetime.now()
        future = now + timedelta(days=365)

        # Parse ICS calendar
        upcoming_events = events(ics_url, start=now, end=future)

        for event in sorted(upcoming_events, key=lambda e: e.start):
            if event.summary and event.start:
                collections = event.summary.split(",")
                for collection in collections:
                    if collection.strip() == "bin collection":
                        collection = "food waste caddy"
                    collection = collection.strip().replace(" collection", "")
                    bindata["bins"].append(
                        {
                            "type": collection,
                            "collectionDate": event.start.date().strftime(date_format),
                        }
                    )

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Hinckley and Bosworth"
URL = "https://www.hinckley-bosworth.gov.uk"
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
