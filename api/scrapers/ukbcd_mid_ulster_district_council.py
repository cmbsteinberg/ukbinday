from __future__ import annotations
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
            user_postcode = kwargs.get('postcode')
            if not user_postcode:
                raise ValueError('No postcode provided.')
            check_postcode(user_postcode)
            user_paon = kwargs.get('paon')
            check_paon(user_paon)
            headless = kwargs.get('headless')
            web_driver = kwargs.get('web_driver')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            page_url = 'https://www.midulstercouncil.org/resident/bins-recycling'
            await page.goto(page_url)
            try:
                accept_cookies_button = page.locator("xpath=//button/span[contains(text(), 'I Accept Cookies')]")
                await accept_cookies_button.click()
            except Exception as e:
                print('Accept cookies button not found or clickable within the specified time.')
                pass
            postcode_input = page.locator('#postcode-search-input')
            await postcode_input.fill(user_postcode)
            postcode_search_btn = page.locator("xpath=//button[contains(text(), 'Go')]")
            await postcode_search_btn.click()
            address_btn = page.locator(f"xpath=//button[contains(text(), '{user_paon}')]")
            await address_btn.press('Enter')
            results_heading = page.locator("xpath=//h3[contains(text(), 'Collection day:')]")
            results = page.locator("xpath=//div/h3[contains(text(), 'My address:')]/parent::div")
            soup = BeautifulSoup(await results.get_attribute('innerHTML'), features='html.parser')
            data = {'bins': []}
            try:
                date_span = soup.select_one('h2.collection-day span.date-text')
                if date_span:
                    date_text = date_span.text.strip()
                    current_year = datetime.now().year
                    full_date = f'{date_text} {current_year}'
                    collection_date = datetime.strptime(full_date, '%d %b %Y').strftime(date_format)
                else:
                    collection_date = None
            except Exception as e:
                print(f'Failed to parse date: {e}')
                collection_date = None
            if collection_date:
                bin_blocks = soup.select('div.bin')
                for bin_block in bin_blocks:
                    bin_title_div = bin_block.select_one('div.bin-title')
                    if bin_title_div:
                        bin_type = bin_title_div.get_text(strip=True)
                        data['bins'].append({'type': bin_type, 'collectionDate': collection_date})
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

TITLE = "Mid Ulster"
URL = "https://www.midulstercouncil.org"
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
