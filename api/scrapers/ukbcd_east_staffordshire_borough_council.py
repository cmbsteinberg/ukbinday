from __future__ import annotations
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
        bindata = {'bins': []}
        soup = BeautifulSoup(page.text, features='html.parser')
        current_year = datetime.now().year
        next_year = current_year + 1
        next_collection_section = soup.find('div', class_='collection-next')
        if next_collection_section:
            next_collection_text = next_collection_section.find('h2').text.strip()
            date_match = re.search('(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), (\\d+)(?:st|nd|rd|th)? (\\w+)', next_collection_text)
            if date_match:
                collection_date = f'{date_match.group(1)} {remove_ordinal_indicator_from_date_string(date_match.group(2))} {date_match.group(3)}'
                collection_date = datetime.strptime(collection_date, '%A %d %B')
                if datetime.now().month == 12 and collection_date.month == 1:
                    collection_date = collection_date.replace(year=next_year)
                else:
                    collection_date = collection_date.replace(year=current_year)
                bins = next_collection_section.find_all('div', class_='field__item')
                for bin_type in bins:
                    dict_data = {'type': bin_type.text.strip(), 'collectionDate': collection_date.strftime(date_format)}
                    bindata['bins'].append(dict_data)
        other_collections = soup.find_all('li')
        for collection in other_collections:
            date_text = collection.contents[0].strip()
            date_match = re.search('(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), (\\d+)(?:st|nd|rd|th)? (\\w+)', date_text)
            if date_match:
                collection_date = f'{date_match.group(1)} {remove_ordinal_indicator_from_date_string(date_match.group(2))} {date_match.group(3)}'
                collection_date = datetime.strptime(collection_date, '%A %d %B')
                if datetime.now().month == 12 and collection_date.month == 1:
                    collection_date = collection_date.replace(year=next_year)
                else:
                    collection_date = collection_date.replace(year=current_year)
                bins = collection.find_all('div', class_='field__item')
                for bin_type in bins:
                    dict_data = {'type': bin_type.text.strip(), 'collectionDate': collection_date.strftime(date_format)}
                    bindata['bins'].append(dict_data)
        bindata['bins'].sort(key=lambda x: datetime.strptime(x.get('collectionDate'), date_format))
        return bindata

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "East Staffordshire"
URL = "https://www.eaststaffsbc.gov.uk/bins-rubbish-recycling/collection-dates/68382"
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
