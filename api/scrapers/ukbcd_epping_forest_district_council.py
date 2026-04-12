from __future__ import annotations
from datetime import datetime
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.common import date_format
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        postcode = kwargs.get('postcode', '')
        web_driver = kwargs.get('web_driver')
        headless = kwargs.get('headless')
        data = {'bins': []}
        try:
            print(f'Initializing webdriver with: {web_driver}, headless: {headless}')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            page_url = f'https://eppingforestdc.maps.arcgis.com/apps/instant/lookup/index.html?appid=bfca32b46e2a47cd9c0a84f2d8cdde17&find={postcode}'
            print(f'Accessing URL: {page_url}')
            await page.goto(page_url)
            try:
                print('Waiting for loading spinner to disappear...')
                await page.locator('.esri-widget--loader-container').wait_for(state='hidden')
            except Exception as e:
                print(f'Loading spinner wait failed (may be normal): {str(e)}')
            print('Waiting for content container...')
            await page.locator('.esri-feature-content').wait_for()
            print('Waiting for content to be visible...')
            content = page.locator('.esri-feature-content')
            if not content:
                raise ValueError('Content element found but empty')
            print('Content found, getting page source...')
            html_content = await page.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            bin_info_divs = soup.select('.esri-feature-content p')
            for div in bin_info_divs:
                if 'collection day is' in div.text:
                    bin_type, date_str = div.text.split(' collection day is ')
                    bin_dates = datetime.strptime(date_str.strip(), '%d/%m/%Y').strftime(date_format)
                    data['bins'].append({'type': bin_type.strip(), 'collectionDate': bin_dates})
            return data
        finally:
            await _ctx.close()

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Epping Forest"
URL = "https://eppingforestdc.maps.arcgis.com/apps/instant/lookup/index.html?appid=bfca32b46e2a47cd9c0a84f2d8cdde17&find=IG9%206EP"
TEST_CASES = {}


class Source:
    def __init__(self, postcode: str | None = None):
        self.postcode = postcode
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.postcode: kwargs['postcode'] = self.postcode

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
