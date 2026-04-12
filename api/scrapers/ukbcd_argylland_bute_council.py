from __future__ import annotations
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

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        """
        Fetch upcoming bin collection types and dates for an Argyll and Bute address.
        
        Parameters:
            page (str): Unused; the function always targets the Argyll and Bute bin collection page.
            **kwargs:
                uprn (str|int): The property UPRN to select (will be normalized to 12 digits).
                postcode (str): The postcode to search.
                web_driver: Optional webdriver configuration or path passed to create_webdriver.
                headless (bool): Whether to run the browser in headless mode.
        
        Returns:
            dict: A dictionary with a "bins" key containing a list of collections. Each collection is a dict with:
                - "type" (str): Human-readable bin type (e.g., "General waste").
                - "collectionDate" (str): Collection date formatted according to the module's `date_format`.
        """
        _ctx = None
        try:
            page_url = 'https://www.argyll-bute.gov.uk/rubbish-and-recycling/household-waste/bin-collection'
            user_uprn = kwargs.get('uprn')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_uprn(user_uprn)
            check_postcode(user_postcode)
            user_uprn = str(user_uprn).zfill(12)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(page_url)
            try:
                accept_cookies = page.locator("xpath=//button[@id='ccc-recommended-settings']")
                await accept_cookies.click()
            except:
                print('Accept cookies banner not found or clickable within the specified time.')
                pass
            postcode_input = page.locator("xpath=//input[@id='edit-postcode']")
            await postcode_input.fill(user_postcode)
            search_btn = page.locator('#edit-submit')
            await search_btn.click()
            address_results = page.locator("xpath=//select[@id='edit-address']")
            await address_results.select_option(value=user_uprn)
            submit_btn = page.locator("xpath=//input[@value='Search for my bin collection details']")
            await submit_btn.click()
            results = page.locator("xpath=//th[contains(text(),'Collection date')]/ancestor::table")
            soup = BeautifulSoup(await results.get_attribute('innerHTML'), features='html.parser')
            today = datetime.today()
            current_year = today.year
            current_month = today.month
            bin_data = {'bins': []}
            for row in soup.find_all('tr')[1:]:
                cells = row.find_all('td')
                if len(cells) < 2:
                    continue
                bin_type = cells[0].get_text(strip=True)
                raw_date = cells[1].get_text(strip=True)
                try:
                    partial_date = datetime.strptime(raw_date, '%A %d %B')
                    month = partial_date.month
                    year = current_year + 1 if month < current_month else current_year
                    full_date_str = f'{raw_date} {year}'
                    parsed_date = datetime.strptime(full_date_str, '%A %d %B %Y')
                    date_str = parsed_date.strftime(date_format)
                except ValueError:
                    continue
                bin_data['bins'].append({'type': bin_type, 'collectionDate': date_str})
            bin_data['bins'].sort(key=lambda x: datetime.strptime(x['collectionDate'], date_format))
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return bin_data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Argyll and Bute"
URL = "https://www.argyll-bute.gov.uk/rubbish-and-recycling/household-waste/bin-collection"
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
