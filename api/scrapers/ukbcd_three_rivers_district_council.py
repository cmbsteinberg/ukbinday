from __future__ import annotations
import logging
from bs4 import BeautifulSoup
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
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            if not headless:
                await page.set_viewport_size({'width': 1920, 'height': 1080})
            await page.goto('https://my.threerivers.gov.uk/en/AchieveForms/?mode=fill&consentMessage=yes&form_uri=sandbox-publish://AF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b/AF-Stage-01ee28aa-1584-442c-8d1f-119b6e27114a/definition.json&process=1&process_uri=sandbox-processes://AF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b&process_id=AF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b&noLoginPrompt=1')
            await page.locator("xpath=//button[contains(text(), 'Continue')]").click()
            logging.info('Switching to iframe')
            iframe_presence = page.locator('#fillform-frame-1')
            
            frame = page.frame_locator('#fillform-frame-1')
            logging.info('Entering postcode')
            input_element_postcode = frame.locator('xpath=//input[@id="postcode_search"]')
            await input_element_postcode.fill(user_postcode)
            logging.info('Selecting address')
            dropdown = frame.locator('#chooseAddress')
            dropdown_options = frame.locator('.lookup-option')
            option_element = frame.locator(f'option.lookup-option[value="{str(user_uprn)}"]')
            await option_element.evaluate('el => el.scrollIntoView()')
            await dropdown.select_option(value=str(user_uprn))
            option_element = frame.locator('xpath=//div[@class="fieldContent"][1]')
            await page.locator("xpath=//button/span[contains(text(), 'Next')]").click()
            logging.info('Waiting for bin schedule')
            bin_results = frame.locator("xpath=//div[@data-field-name='subCollectionCalendar']//table")
            logging.info('Extracting bin collection data')
            soup = BeautifulSoup(await page.content(), features='html.parser')
            bin_cards = soup.find_all('div', {'data-field-name': 'subCollectionCalendar'})
            bins = []
            for bin_card in bin_cards:
                table = bin_card.find('table', {'class': 'repeatable-table table table-responsive table-hover table-condensed'})
                if table:
                    print('Table found')
                    rows = table.select('tr.repeatable-value')
                    for row in rows:
                        cols = row.find_all('td', class_='value')
                        if len(cols) >= 3:
                            bin_type = cols[1].find_all('span')[-1].text.strip()
                            collection_date = cols[2].find_all('span')[-1].text.strip().replace('-', '/')
                            bins.append({'type': bin_type, 'collectionDate': collection_date})
                else:
                    print('Table not found within bin_card')
            bin_data = {'bins': bins}
            logging.info('Data extraction complete')
            return bin_data
        except Exception as e:
            logging.error(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Three Rivers"
URL = "https://my.threerivers.gov.uk/en/AchieveForms/?mode=fill&consentMessage=yes&form_uri=sandbox-publish://AF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b/AF-Stage-01ee28aa-1584-442c-8d1f-119b6e27114a/definition.json&process=1&process_uri=sandbox-processes://AF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b&process_id=AF-Process-52df96e3-992a-4b39-bba3-06cfaabcb42b&noLoginPrompt=1"
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
