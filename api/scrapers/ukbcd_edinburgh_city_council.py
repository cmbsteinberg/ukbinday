from __future__ import annotations
import re
import httpx
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        """
        Produce scheduled bin collection entries for a property based on a reference weekday and fortnightly rota.
        
        Parameters:
            page (str): The page content passed to the parser (not used for scheduling).
            paon (str, in kwargs): The reference weekday name (e.g., "Monday") representing the property's collection day.
            postcode (str, in kwargs): The collection week label, either "Week 1" or "Week 2", used to select rota start dates.
        
        Returns:
            dict: A mapping with a single key "bins" whose value is a list of collection entries.
                Each entry is a dict with:
                    - "type" (str): Bin type name ("Grey Bin", "Green Bin", or "Glass Box").
                    - "collectionDate" (str): Collection date in "DD/MM/YYYY" format.
        """
        collection_day = kwargs.get('paon')
        collection_week = kwargs.get('postcode')
        bindata = {'bins': []}
        days_of_week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        collection_weeks = ['Week 1', 'Week 2']
        collection_week = collection_weeks.index(collection_week)
        offset_days = days_of_week.index(collection_day)
        if collection_week == 0:
            recyclingstartDate = datetime(2025, 11, 3)
            glassstartDate = datetime(2025, 11, 3)
            refusestartDate = datetime(2025, 11, 10)
        elif collection_week == 1:
            recyclingstartDate = datetime(2025, 11, 10)
            glassstartDate = datetime(2025, 11, 10)
            refusestartDate = datetime(2025, 11, 3)
        refuse_dates = get_dates_every_x_days(refusestartDate, 14, 28)
        glass_dates = get_dates_every_x_days(glassstartDate, 14, 28)
        recycling_dates = get_dates_every_x_days(recyclingstartDate, 14, 28)
        for refuseDate in refuse_dates:
            collection_date = (datetime.strptime(refuseDate, '%d/%m/%Y') + timedelta(days=offset_days)).strftime('%d/%m/%Y')
            dict_data = {'type': 'Grey Bin', 'collectionDate': collection_date}
            bindata['bins'].append(dict_data)
        for recyclingDate in recycling_dates:
            collection_date = (datetime.strptime(recyclingDate, '%d/%m/%Y') + timedelta(days=offset_days)).strftime('%d/%m/%Y')
            dict_data = {'type': 'Green Bin', 'collectionDate': collection_date}
            bindata['bins'].append(dict_data)
        for glassDate in glass_dates:
            collection_date = (datetime.strptime(glassDate, '%d/%m/%Y') + timedelta(days=offset_days)).strftime('%d/%m/%Y')
            dict_data = {'type': 'Glass Box', 'collectionDate': collection_date}
            bindata['bins'].append(dict_data)
        bindata['bins'].sort(key=lambda x: datetime.strptime(x.get('collectionDate'), '%d/%m/%Y'))
        return bindata

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "City of Edinburgh"
URL = "https://www.edinburgh.gov.uk"
TEST_CASES = {}


class Source:
    def __init__(self, postcode: str | None = None, house_number: str | None = None):
        self.postcode = postcode
        self.house_number = house_number
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.postcode: kwargs['postcode'] = self.postcode
        if self.house_number: kwargs['paon'] = self.house_number

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
