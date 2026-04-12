from __future__ import annotations
import re
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

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        try:
            headless = kwargs.get('headless')
            web_driver = kwargs.get('web_driver')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(kwargs.get('url'))
            await page.locator('.waste-service-name').wait_for()
            data = {'bins': []}
            soup = BeautifulSoup(await page.content(), 'html.parser')
            service_grids = soup.find_all('div', {'class': 'waste-service-grid'})
            if not service_grids:
                raise ValueError('Kingston parser: no waste-service-grid elements found on page')
            for grid in service_grids:
                service_name_elem = grid.find('h3', {'class': 'waste-service-name'})
                if not service_name_elem:
                    raise ValueError('Kingston parser: missing h3.waste-service-name in waste-service-grid')
                service_name = service_name_elem.get_text().strip()
                summary_list = grid.find('dl', {'class': 'govuk-summary-list'})
                if not summary_list:
                    raise ValueError(f'Kingston parser: missing dl.govuk-summary-list for {service_name}')
                rows = summary_list.find_all('div', {'class': 'govuk-summary-list__row'})
                for row in rows:
                    dt = row.find('dt')
                    if dt and dt.get_text().strip().lower() == 'next collection':
                        dd = row.find('dd')
                        if not dd:
                            raise ValueError(f"Kingston parser: missing dd element for 'next collection' in {service_name}")
                        collection_date = remove_ordinal_indicator_from_date_string(dd.get_text()).strip().replace(' (In progress)', '')
                        collection_date = re.sub('\\n\\s*\\(this.*?\\)', '', collection_date)
                        dict_data = {'type': service_name, 'collectionDate': get_next_occurrence_from_day_month(datetime.strptime(collection_date + ' ' + datetime.now().strftime('%Y'), '%A, %d %B %Y')).strftime(date_format)}
                        data['bins'].append(dict_data)
            data['bins'].sort(key=lambda x: datetime.strptime(x.get('collectionDate'), date_format))
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Kingston upon Thames"
URL = "https://waste-services.kingston.gov.uk/waste/2701097"
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
