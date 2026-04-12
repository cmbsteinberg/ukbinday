from __future__ import annotations
import re
from datetime import datetime, timedelta
import httpx
from bs4 import BeautifulSoup
from icalevents.icalevents import events
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):

    async def parse_data(self, page: str, **kwargs) -> dict:
        """
        Fetch upcoming bin collections for a property and return them as structured data.
        
        Parses an ICS calendar URL constructed from the provided `uprn` to collect events occurring within the next 60 days and returns each collection entry with its type and formatted collection date.
        
        Parameters:
            uprn (str): Unique Property Reference Number used to build the council's ICS calendar URL.
        
        Returns:
            dict: A dictionary with a single key `"bins"` containing a list of collection records. Each record is a dict with:
                - "type" (str): Collection type/name.
                - "collectionDate" (str): Collection date formatted according to `date_format`.
        """
        _ctx = None
        try:
            data = {'bins': []}
            user_uprn = kwargs.get('uprn')
            check_uprn(user_uprn)
            ics_url = f'https://www.dumfriesandgalloway.gov.uk/bins-recycling/waste-collection-schedule/download/{user_uprn}'
            now = datetime.now()
            future = now + timedelta(days=60)
            upcoming_events = events(ics_url, start=now, end=future)
            for event in sorted(upcoming_events, key=lambda e: e.start):
                if event.summary and event.start:
                    collections = event.summary.split(',')
                    for collection in collections:
                        data['bins'].append({'type': collection.strip(), 'collectionDate': event.start.date().strftime(date_format)})
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Dumfries and Galloway Council"
URL = "https://www.dumfriesandgalloway.gov.uk"
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
