from __future__ import annotations
from bs4 import BeautifulSoup
from datetime import datetime
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        try:
            bindata = {'bins': []}
            user_paon = kwargs.get('paon')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_paon(user_paon)
            check_postcode(user_postcode)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.set_viewport_size({'width': 1920, 'height': 1080})
            await page.goto('https://www.knowsley.gov.uk/bins-waste-and-recycling/your-household-bins/putting-your-bins-out')
            try:
                accept_cookies = page.locator("xpath=//a[contains(@class, 'agree-button') and contains(text(), 'Accept all cookies')]")
                await accept_cookies.click()
            except:
                pass
            search_btn = page.locator("xpath=//a[contains(text(), 'Search\xa0by postcode\xa0to find out when your bins are emptied')]")
            await search_btn.press('Enter')
            postcode_box = page.locator("xpath=//label[contains(text(), 'Please enter the post code')]/following-sibling::input")
            await postcode_box.fill(user_postcode)
            postcode_search_btn = page.locator("xpath=//label[contains(text(), 'Please enter the post code')]/parent::div/following-sibling::button")
            await postcode_search_btn.press('Enter')
            address_selection_button = page.locator(f"xpath=//span[contains(text(), '{user_paon}')]/ancestor::li//button")
            await address_selection_button.press('Enter')
            await page.locator("xpath=//label[contains(text(), 'collection')]").wait_for()
            bin_info_container = page.locator("xpath=//label[contains(text(), 'collection')]/ancestor::div[contains(@class, 'mx-dataview-content')]").first
            soup = BeautifulSoup(await bin_info_container.get_attribute('innerHTML'), 'html.parser')
            for group in soup.find_all('div', class_='form-group'):
                label = group.find('label')
                value = group.find('div', class_='form-control-static')
                if not label or not value:
                    continue
                label_text = label.text.strip()
                value_text = value.text.strip()
                if 'bin next collection date' in label_text.lower():
                    bin_type = label_text.split(' bin')[0]
                    try:
                        collection_date = datetime.strptime(value_text, '%A %d/%m/%Y').strftime('%d/%m/%Y')
                    except ValueError:
                        continue
                    bindata['bins'].append({'type': bin_type, 'collectionDate': collection_date})
            bindata['bins'].sort(key=lambda x: datetime.strptime(x['collectionDate'], '%d/%m/%Y'))
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return bindata

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Knowsley"
URL = "https://knowsleytransaction.mendixcloud.com/link/youarebeingredirected?target=bincollectioninformation"
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
