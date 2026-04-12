from __future__ import annotations
import datetime
import re
from datetime import datetime
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
        """
        Fetch and parse bin collection data for a given address from Brighton & Hove's collections page.
        
        This function drives a Selenium browser to the fixed Brighton & Hove collections URL, submits the provided postcode, selects the matching PAON (primary addressable object name) from the resulting address dropdown, submits the selection, and parses the resulting list view into structured bin collection entries.
        
        Parameters:
            page (str): Unused; included for compatibility with caller signature.
            uprn (str, optional): Unique Property Reference Number for the address (passed via kwargs).
            paon (str, optional): Primary addressable object name used to match and select the address from dropdown (passed via kwargs).
            postcode (str, optional): Postcode to search on the council site (passed via kwargs).
            web_driver (str or WebDriver, optional): Specification or instance used by create_webdriver to start the browser (passed via kwargs).
            headless (bool, optional): Whether to run the browser in headless mode (passed via kwargs).
        
        Returns:
            dict: A dictionary with a single key "bins" whose value is a list of objects each containing:
                - "type": bin type string
                - "collectionDate": collection date string formatted according to the module's date_format
        
        Raises:
            Exception: If no dropdown option matching `paon` is found or any other error occurs during navigation or parsing.
        """
        _ctx = None
        try:
            data = {'bins': []}
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)'}
            url = 'https://enviroservices.brighton-hove.gov.uk/link/collections'
            uprn = kwargs.get('uprn')
            user_paon = kwargs.get('paon')
            postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(url)
            post_code_search = page.locator('.form-control')
            await post_code_search.fill(postcode)
            submit_btn = page.locator(f"xpath=//button[contains(@class, 'mx-name-actionButton3')]")
            await submit_btn.press('Enter')
            dropdown_options = page.locator(f'xpath=//option[contains(text(), "{user_paon}")]')
            parent_element = dropdown_options.locator('xpath=..').first
            options = await parent_element.locator('option').all()
            found = False
            for option in options:
                if user_paon in await option.text_content():
                    await option.click()
                    found = True
                    break
            if not found:
                raise Exception(f"Address containing '{user_paon}' not found in dropdown options")
            submit_btn = page.locator(f"xpath=//button[contains(@class, 'mx-name-actionButton5')]")
            await submit_btn.press('Enter')
            results = page.locator(f'xpath=//div[contains(@class,"mx-name-listView1")]')
            soup = BeautifulSoup(await page.content(), features='html.parser')
            data = {'bins': []}
            current_date = datetime.now()
            bin_view = soup.find(class_='mx-name-listView1')
            bins = bin_view.find_all(class_=lambda x: x and x.startswith('mx-name-index-'))
            for bin_item in bins:
                bin_type = bin_item.find(class_='mx-name-text31').text.strip()
                bin_date_str = bin_item.find(class_='mx-name-text29').text.strip()
                bin_date = datetime.strptime(bin_date_str, '%d %B %Y')
                bin_date = bin_date.strftime(date_format)
                dict_data = {'type': bin_type, 'collectionDate': bin_date}
                data['bins'].append(dict_data)
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Brighton and Hove"
URL = "https://enviroservices.brighton-hove.gov.uk/link/collections"
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
