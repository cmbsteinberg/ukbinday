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

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        try:
            user_paon = kwargs.get('paon')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_paon(user_paon)
            check_postcode(user_postcode)
            bindata = {'bins': []}
            URI = 'https://hertsmere-services.onmats.com/w/webpage/round-search'
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(URI)
            inputElement_postcode = page.locator('.relation_path_type_ahead_search')
            await inputElement_postcode.fill(user_postcode)
            await page.locator('ul.result_list li').wait_for()
            await page.evaluate(f"\n                const results = document.querySelectorAll('ul.result_list li');\n                for (let li of results) {{\n                    const ariaLabel = li.getAttribute('aria-label');\n                    if (ariaLabel && ariaLabel.startsWith('{user_paon} ')) {{\n                        li.click();\n                        return;\n                    }}\n                }}\n            ")
            await page.locator("input.fragment_presenter_template_edit.btn.bg-primary.btn-medium[type='submit']").click()
            await page.locator("xpath=//h3[contains(text(), 'Collection days')]").wait_for()
            soup = BeautifulSoup(await page.content(), 'html.parser')
            table = soup.find('table', class_='table listing table-striped')
            if not table:
                raise Exception('Collection schedule table not found.')
            table_data = []
            for row in table.find('tbody').find_all('tr'):
                row_data = [cell.get_text(strip=True) for cell in row.find_all('td')]
                table_data.append(row_data)
            if not table_data or len(table_data[0]) < 2:
                raise Exception('Unable to parse collection schedule from table.')
            collection_day = table_data[0][1]
            bin_types = []
            for row in table_data:
                if len(row) >= 1 and row[0].strip():
                    bin_types.append(row[0].strip())
            from datetime import datetime, timedelta
            days_of_week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            today = datetime.now()
            today_idx = today.weekday()
            target_idx = days_of_week.index(collection_day)
            days_until_target = (target_idx - today_idx) % 7
            if days_until_target == 0:
                next_day = today
            else:
                next_day = today + timedelta(days=days_until_target)
            all_dates = get_dates_every_x_days(next_day, 7, 12)
            for date in all_dates:
                for bin_type in bin_types:
                    dict_data = {'type': bin_type, 'collectionDate': date}
                    bindata['bins'].append(dict_data)
            bindata['bins'].sort(key=lambda x: datetime.strptime(x.get('collectionDate'), '%d/%m/%Y'))
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return bindata

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Hertsmere"
URL = "https://www.hertsmere.gov.uk"
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
