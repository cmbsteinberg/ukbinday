from __future__ import annotations
import logging
import pickle
import httpx
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class CouncilClass(AbstractGetBinDataClass):

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        try:
            data = {'bins': []}
            collections = []
            user_uprn = kwargs.get('uprn')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_postcode(user_postcode)
            url = 'https://selfservice.wychavon.gov.uk/wdcroundlookup/wdc_search.jsp'
            user_agent = 'general.useragent.override", "userAgent=Mozilla/5.0 \n            (iPhone; CPU iPhone OS 15_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like \n            Gecko) CriOS/101.0.4951.44 Mobile/15E148 Safari/604.1'
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(url)
            logging.info('Accepting cookies')
            try:
                logging.info('Cookies')
                cookie_window = page.locator('xpath=//div[@id="ccc-content"]')
                accept_cookies = page.locator('xpath=//button[@id="ccc-recommended-settings"]')
                await accept_cookies.press('Enter')
                await accept_cookies.click()
                accept_cookies_close = page.locator('xpath=//button[@id="ccc-close"]')
                await accept_cookies_close.press('Enter')
                await accept_cookies_close.click()
            except:
                print('Accept cookies banner not found or clickable within the specified time.')
                pass
            logging.info('Entering postcode')
            input_element_postcode = page.locator('xpath=//input[@id="alAddrtxt"]')
            await input_element_postcode.fill(user_postcode)
            logging.info('Searching for postcode')
            input_element_postcode_btn = page.locator('xpath=//button[@id="alAddrbtn"]')
            await input_element_postcode_btn.click()
            logging.info('Waiting for address dropdown')
            input_element_postcode_dropdown = page.locator('xpath=//select[@id="alAddrsel"]')
            logging.info('Selecting address')
            option_element = page.locator(f'option[value="{str(user_uprn)}"]')
            await option_element.evaluate('el => el.scrollIntoView()')
            await input_element_postcode_dropdown.select_option(value=str(user_uprn))
            input_element_address_btn = page.locator('xpath=//input[@id="btnSubmit"]')
            await input_element_address_btn.click()
            logging.info('Waiting for bin collection page')
            strong_element = page.locator("xpath=//strong[contains(text(), 'Upcoming collections')]")
            logging.info('Extracting bin collection data')
            soup = BeautifulSoup(await page.content(), features='html.parser')
            bins = []
            rows = soup.select('table tbody tr')
            for row in rows:
                bin_type = row.select_one('td:nth-of-type(2)').contents[0].strip()
                date_elements = row.select('td:nth-of-type(3) strong')
                if date_elements:
                    dates = [date.get_text(strip=True) for date in date_elements]
                else:
                    dates = ['Not applicable']
                for date in dates:
                    if date != 'Not applicable':
                        formatted_date = re.search('\\d{2}/\\d{2}/\\d{4}', date).group(0)
                        bins.append({'type': bin_type, 'collectionDate': formatted_date})
            bin_data = {'bins': bins}
            return bin_data
        except Exception as e:
            logging.error(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Wychavon"
URL = "https://selfservice.wychavon.gov.uk/wdcroundlookup/wdc_search.jsp"
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
