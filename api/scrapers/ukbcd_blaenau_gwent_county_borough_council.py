from __future__ import annotations
from bs4 import BeautifulSoup
import re
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        try:
            data = {'bins': []}
            user_uprn = kwargs.get('uprn')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_uprn(user_uprn)
            check_postcode(user_postcode)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto('https://www.blaenau-gwent.gov.uk/en/resident/waste-recycling/')
            try:
                await page.locator('#ccc-overlay').wait_for()
                cookie_buttons = ["//button[contains(text(), 'Accept')]", "//button[contains(text(), 'OK')]", "//button[@id='ccc-recommended-settings']", "//button[contains(@class, 'cookie')]"]
                for button_xpath in cookie_buttons:
                    try:
                        cookie_button = page.locator(f'xpath={button_xpath}').first
                        if cookie_button.is_displayed():
                            await cookie_button.click()
                            break
                    except:
                        continue
            except:
                pass
            find_collection_link = page.locator("xpath=//a[contains(text(), 'Find Your Collection Day')]")
            collection_url = await find_collection_link.get_attribute('href')
            await page.goto(collection_url)
            postcode_input = page.locator('#postcodeSearch')
            await postcode_input.fill(user_postcode)
            find_button = page.locator("xpath=//button[contains(text(), 'Find')]")
            await find_button.click()
            await page.locator('#addressSelect').wait_for()
            dropdown = page.locator('#addressSelect')
            await dropdown.select_option(value=user_uprn)
            soup = BeautifulSoup(await page.content(), features='html.parser')
            page_text = soup.get_text()
            if 'Your next collections' in page_text:
                collections_section = page_text.split('Your next collections')[1]
                collections_section = collections_section.split('Related content')[0]
                pattern = '(Recycling collection|Refuse Bin)([A-Za-z]+ \\d+ [A-Za-z]+)(?=followed|$|[A-Z])'
                matches = re.findall(pattern, collections_section)
                for bin_type, date_text in matches:
                    try:
                        date_text = date_text.strip()
                        if 'followed by' in date_text:
                            date_text = date_text.split('followed by')[0].strip()
                        collection_date = datetime.strptime(date_text, '%A %d %B')
                        current_year = datetime.now().year
                        current_month = datetime.now().month
                        if current_month > 10 and collection_date.month < 3:
                            collection_date = collection_date.replace(year=current_year + 1)
                        else:
                            collection_date = collection_date.replace(year=current_year)
                        dict_data = {'type': bin_type, 'collectionDate': collection_date.strftime('%d/%m/%Y')}
                        data['bins'].append(dict_data)
                    except ValueError:
                        pass
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Blaenau Gwent"
URL = "https://www.blaenau-gwent.gov.uk"
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
