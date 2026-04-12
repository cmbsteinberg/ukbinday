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
        """
        Retrieve bin collection types and upcoming collection dates for the given address.
        
        Parameters:
            page (str): Unused by this implementation (kept for interface compatibility).
            paon (str, in kwargs): Property/PAON text used to select the correct address option.
            postcode (str, in kwargs): Postcode to search for addresses.
            web_driver (optional, in kwargs): Selenium WebDriver instance or web driver identifier to use when creating the driver.
            headless (bool, optional, in kwargs): Whether to run the browser in headless mode.
        
        Returns:
            data (dict): Dictionary with a single key "bins" whose value is a list of dictionaries. Each entry contains:
                - "type" (str): The bin/collection type name.
                - "collectionDate" (str): The next collection date formatted according to the module's date_format.
        """
        _ctx = None
        try:
            data = {'bins': []}
            user_paon = kwargs.get('paon')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_paon(user_paon)
            check_postcode(user_postcode)
            user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto('https://www.boston.gov.uk/findwastecollections')
            try:
                accept_button = page.locator('[name="acceptall"]')
                await accept_button.click()
            except (TimeoutError, ElementClickInterceptedException):
                pass
            inputElement_postcode = page.locator('#BBCWASTECOLLECTIONSV2_COLLECTIONS_SEARCHPOSTCODE')
            await inputElement_postcode.fill(user_postcode)
            findAddress = page.locator('#BBCWASTECOLLECTIONSV2_COLLECTIONS_START10_NEXT')
            await findAddress.click()
            await page.locator("xpath=//select[contains(@id, 'ADDRESSSELECTION')] | //div[contains(@id, 'chosen')]").wait_for()
            try:
                address_select = page.locator("xpath=//select[contains(@id, 'ADDRESSSELECTION')]").first
                option = page.locator(f"xpath=//select[contains(@id, 'ADDRESSSELECTION')]//option[contains(text(), '{user_paon}')]").first
                await option.click()
            except TimeoutError:
                dropdown = page.locator("xpath=//div[contains(@id, 'chosen')]").first
                await dropdown.click()
                await page.locator('.chosen-results').wait_for()
                desired_option = page.locator(f"xpath=//li[@class='active-result' and contains(text(), '{user_paon}')]").first
                await desired_option.click()
            next_button = page.locator("xpath=//button[contains(@id, 'NEXT') and contains(@id, 'BBCWASTECOLLECTIONSV2')]")
            await next_button.click()
            await page.locator("xpath=//div[contains(@class, 'item__title') or contains(@class, 'grid__cell--listitem')]").wait_for()
            soup = BeautifulSoup(await page.content(), features='html.parser')
            bins = soup.find_all('div', class_='grid__cell grid__cell--listitem grid__cell--cols1')
            current_year = datetime.now().year
            next_year = current_year + 1
            for bin_div in bins:
                bin_type_elem = bin_div.find('h2', class_='item__title')
                if not bin_type_elem:
                    continue
                bin_type = bin_type_elem.text.strip()
                content_div = bin_div.find('div', class_='item__content')
                if not content_div:
                    continue
                date_div = content_div.find('div')
                if not date_div:
                    continue
                next_collection = date_div.text.strip().replace('Next: ', '')
                next_collection = datetime.strptime(remove_ordinal_indicator_from_date_string(next_collection), '%A %d %B')
                if datetime.now().month == 12 and next_collection.month == 1:
                    next_collection = next_collection.replace(year=next_year)
                else:
                    next_collection = next_collection.replace(year=current_year)
                dict_data = {'type': bin_type, 'collectionDate': next_collection.strftime(date_format)}
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

TITLE = "Boston"
URL = "https://www.boston.gov.uk/findwastecollections"
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
