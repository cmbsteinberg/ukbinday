from __future__ import annotations
import logging
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class CouncilClass(AbstractGetBinDataClass):

    def get_legacy_bins(self, page: str) -> []:
        logging.info('Extracting legacy bin collection data')
        soup = BeautifulSoup(page, features='html.parser')
        legacy_bins = []
        rubbish_recycling = soup.find('span', class_='CTID-77-_ eb-77-Override-textControl')
        if rubbish_recycling:
            match = re.search('collected weekly on (\\w+)', rubbish_recycling.text)
            if match:
                day_name = match.group(1)
                next_collection = get_next_day_of_week(day_name)
                legacy_bins.append({'type': 'Rubbish and recycling', 'collectionDate': next_collection})
                logging.info(f'Rubbish and Recycling: {str(next_collection)}')
        glass_collection = soup.find('span', class_='CTID-78-_ eb-78-textControl')
        if glass_collection:
            match = re.search('next collection is\\s+(\\d{2}/\\d{2}/\\d{4})', glass_collection.text)
            if match:
                legacy_bins.append({'type': 'Glass collection', 'collectionDate': match.group(1)})
                logging.info(f'Glass: {str(match.group(1))}')
        garden_waste = soup.find('div', class_='eb-2HIpCnWC-Override-EditorInput')
        if garden_waste:
            match = re.search('(\\d{2}/\\d{2}/\\d{4})', garden_waste.text)
            if match:
                legacy_bins.append({'type': 'Garden waste', 'collectionDate': match.group(1)})
                logging.info(f'Garden: {str(match.group(1))}')
        return legacy_bins

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        try:
            bins = []
            user_uprn = kwargs.get('uprn')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_postcode(user_postcode)
            url = 'https://forms.newforest.gov.uk/ufs/FIND_MY_BIN_BAR.eb'
            user_agent = 'general.useragent.override", "userAgent=Mozilla/5.0 \n            (iPhone; CPU iPhone OS 15_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like \n            Gecko) CriOS/101.0.4951.44 Mobile/15E148 Safari/604.1'
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(url)
            await page.reload()
            logging.info('Entering postcode')
            input_element_postcode = page.locator('xpath=//input[@id="CTID-JmLqCKl2-_-A"]')
            await input_element_postcode.evaluate('el => el.scrollIntoView()')
            logging.info(f"Entering postcode '{str(user_postcode)}'")
            await page.evaluate(f"arguments[0].value='{str(user_postcode)}'", input_element_postcode)
            logging.info('Searching for postcode')
            input_element_postcode_btn = page.locator('xpath=//input[@type="submit"]')
            await input_element_postcode_btn.click()
            logging.info('Waiting for address dropdown')
            input_element_postcode_dropdown = page.locator('xpath=//select[@id="CTID-KOeKcmrC-_-A"]')
            logging.info('Selecting address')
            option_element = page.locator(f'option[value="{str(user_uprn)}"]')
            await option_element.evaluate('el => el.scrollIntoView()')
            await input_element_postcode_dropdown.select_option(value=str(user_uprn))
            input_element_address_btn = page.locator('xpath=//input[@value="Submit"]')
            await input_element_address_btn.click()
            try:
                link_element = page.locator('xpath=//a[contains(text(),"Find your current bin collection day")]').first
                logging.info('Found override panel span, search for link and use old logic')
                await link_element.click()
                bins = self.get_legacy_bins(await page.content())
            except TimeoutError:
                logging.info('Waiting for bin collection table')
                collections_table = page.locator('xpath=//table[contains(@class,"eb-1j4UaesZ-tableContent")]')
                soup = BeautifulSoup(await page.content(), features='html.parser')
                rows = soup.find_all(class_='eb-1j4UaesZ-tableRow')
                for row in rows:
                    cols = row.find_all('td')
                    date_string = cols[0].findChild('div').findChild('div').get_text()
                    bin_type = cols[1].findChild('div').findChild('div').get_text()
                    col_date = datetime.strptime(date_string, '%A %B %d, %Y')
                    bins.append({'type': bin_type, 'collectionDate': datetime.strftime(col_date, date_format)})
            return {'bins': bins}
        except Exception as e:
            logging.error(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "New Forest"
URL = "https://forms.newforest.gov.uk/ufs/FIND_MY_BIN_BAR.eb"
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
