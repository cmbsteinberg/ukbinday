from __future__ import annotations
import datetime
import time
from datetime import datetime
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

    def extract_styles(self, style_str: str) -> dict:
        """
        Parse an inline CSS style string into a dictionary of property-value pairs.
        
        Parameters:
            style_str (str): Inline CSS style text with semicolon-separated declarations (e.g. "color: red; margin: 0;").
        
        Returns:
            dict: Mapping of CSS property names to their values, with surrounding whitespace removed from both keys and values.
        """
        return dict(((a.strip(), b.strip()) for a, b in (element.split(':') for element in style_str.split(';') if element)))

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        """
        Fetches bin collection dates from the Northumberland council postcode lookup and returns them as structured entries.
        
        Parameters:
            page (str): Ignored; the method uses the council postcode lookup URL.
            **kwargs:
                postcode (str): UK postcode to query.
                uprn (str|int): Property UPRN; will be padded to 12 digits before use.
                web_driver: Optional Selenium WebDriver factory or identifier passed to create_webdriver.
                headless (bool): Optional flag controlling headless browser creation.
        
        Returns:
            dict: A dictionary with a "bins" key mapping to a list of entries. Each entry is a dict with:
                - "type" (str): The bin type (e.g., "General waste", "Recycling", "Garden waste").
                - "collectionDate" (str): The collection date formatted according to the module's date_format.
        """
        _ctx = None
        try:
            page_url = 'https://bincollection.northumberland.gov.uk/postcode'
            data = {'bins': []}
            user_postcode = kwargs.get('postcode')
            user_uprn = kwargs.get('uprn')
            check_postcode(user_postcode)
            check_uprn(user_uprn)
            user_uprn = str(user_uprn).zfill(12)
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(page_url)
            cookie_button = page.locator('.accept-all')
            await cookie_button.click()
            inputElement_pc = page.locator('#postcode')
            await inputElement_pc.fill(user_postcode)
            submit_button = page.locator('.govuk-button')
            await submit_button.click()
            selectElement_address = page.locator('#address')
            await selectElement_address.select_option(value=user_uprn)
            submit_button = page.locator('.govuk-button')
            await submit_button.click()
            route_summary = page.locator('.govuk-table')
            now = datetime.now()
            current_month = now.month
            current_year = now.year
            soup = BeautifulSoup(await page.content(), features='html.parser')
            rows = soup.find('tbody', class_='govuk-table__body').find_all('tr', class_='govuk-table__row')
            for row in rows:
                bin_type = row.find_all('td')[-1].text.strip()
                collection_date_string = row.find('th').text.strip()
                collection_date_day = ''.join([i for i in list(collection_date_string.split(' ')[0]) if i.isdigit()])
                collection_date_month_name = collection_date_string.split(' ')[1]
                if current_month >= 10 and collection_date_month_name in ['January', 'February', 'March']:
                    collection_date_year = current_year + 1
                else:
                    collection_date_year = current_year
                collection_date = time.strptime(f'{collection_date_day} {collection_date_month_name} {collection_date_year}', '%d %B %Y')
                data['bins'].append({'type': bin_type, 'collectionDate': time.strftime(date_format, collection_date)})
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Northumberland"
URL = "https://bincollection.northumberland.gov.uk/postcode"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None, postcode: str | None = None):
        self.uprn = uprn
        self.postcode = postcode
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn
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
