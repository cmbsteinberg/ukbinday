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
        Parse Winchester council bin calendar and extract upcoming collection types and dates.
        
        Parameters:
            page (str): Unused by this implementation; kept for interface compatibility.
            **kwargs:
                paon (str): Property name or number to match in the address selection.
                postcode (str): Postcode to search for addresses.
                web_driver: Optional identifier or configuration for the Selenium webdriver.
                headless (bool): Whether to run the webdriver in headless mode.
        
        Returns:
            dict: A dictionary with a single key "bins" whose value is a list of dictionaries, each containing:
                - "type" (str): The bin type/name.
                - "collectionDate" (str): Collection date formatted as "dd/mm/YYYY".
        
        Raises:
            ValueError: If the page does not contain the expected collections container.
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
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto('http://www.winchester.gov.uk/bin-calendar')
            inputElement_postcode = page.locator('#postcodeSearch')
            await inputElement_postcode.fill(user_postcode)
            findAddress = page.locator('xpath=//button[@class="govuk-button mt-4"]')
            await findAddress.click()
            await page.locator(f"""xpath={"//select[@id='addressSelect']//option[contains(., '" + user_paon + "')]"}""").click()
            await page.locator('xpath=//div[contains(@class, "ant-row") and contains(@class, "justify-content-between")]').wait_for()
            soup = BeautifulSoup(await page.content(), features='html.parser')
            recyclingcalendar = soup.find('div', class_=lambda c: c and 'ant-row' in c and ('justify-content-between' in c))
            if not recyclingcalendar:
                raise ValueError('Could not find the collections container on the page')
            cards = recyclingcalendar.find_all('div', class_=lambda c: c and 'p-2' in c and ('flex-column' in c))
            current_year = datetime.now().year
            current_month = datetime.now().month
            for card in cards:
                h3 = card.find('h3')
                if not h3:
                    continue
                BinType = h3.text.strip()
                date_div = card.find('div', class_=lambda c: c and 'fw-bold' in c)
                if not date_div:
                    continue
                date_text = date_div.text.strip()
                collectiondate = datetime.strptime(date_text, '%A %d %B')
                if current_month > 10 and collectiondate.month < 3:
                    collectiondate = collectiondate.replace(year=current_year + 1)
                else:
                    collectiondate = collectiondate.replace(year=current_year)
                dict_data = {'type': BinType, 'collectionDate': collectiondate.strftime('%d/%m/%Y')}
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

TITLE = "Winchester"
URL = "https://iportal.itouchvision.com/icollectionday/collection-day"
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
