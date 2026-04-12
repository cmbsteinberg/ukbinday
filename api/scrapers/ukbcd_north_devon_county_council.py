from __future__ import annotations
from time import sleep
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the base
    class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        try:
            user_uprn = kwargs.get('uprn')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_uprn(user_uprn)
            check_postcode(user_postcode)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto('https://my.northdevon.gov.uk/service/WasteRecyclingCollectionCalendar')
            page.frame_locator('#fillform-frame-1')
            postcode = page.locator('#postcode_search')
            await postcode.fill(user_postcode.replace(' ', ''))
            address = page.locator('#chooseAddress')
            await page.locator('.spinner-outer').wait_for(state='hidden')
            sleep(2)
            await address.select_option(value=user_uprn)
            await page.locator('.spinner-outer').wait_for(state='hidden')
            sleep(2)
            address_confirmation = page.locator("xpath=//h2[contains(text(), 'Your address')]")
            next_button = page.locator("xpath=//button/span[contains(@class, 'nextText')]")
            await next_button.click()
            results = page.locator("xpath=//h4[contains(text(), 'Key')]")
            data_table = page.locator('xpath=//div[@data-field-name="html1"]/div[contains(@class, "fieldContent")]')
            soup = BeautifulSoup(await data_table.get_attribute('innerHTML'), features='html.parser')
            data = {'bins': []}
            waste_sections = soup.find_all('ul', class_='wasteDates')
            current_month_year = None
            for section in waste_sections:
                for li in section.find_all('li', recursive=False):
                    if 'MonthLabel' in li.get('class', []):
                        header = li.find('h4')
                        if header:
                            current_month_year = header.text.strip()
                    elif any((bin_class in li.get('class', []) for bin_class in ['BlackBin', 'GreenBin', 'Recycling'])):
                        bin_type = li.find('span', class_='wasteType').text.strip()
                        day = li.find('span', class_='wasteDay').text.strip()
                        weekday = li.find('span', class_='wasteName').text.strip()
                        if current_month_year and day:
                            try:
                                full_date = f'{day} {current_month_year}'
                                collection_date = datetime.strptime(full_date, '%d %B %Y').strftime(date_format)
                                dict_data = {'type': bin_type, 'collectionDate': collection_date}
                                data['bins'].append(dict_data)
                            except Exception as e:
                                print(f"Skipping invalid date '{full_date}': {e}")
            data['bins'].sort(key=lambda x: datetime.strptime(x.get('collectionDate'), date_format))
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "North Devon"
URL = "https://my.northdevon.gov.uk/service/WasteRecyclingCollectionCalendar"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None, postcode: str | None = None, house_number: str | None = None):
        self.uprn = uprn
        self.postcode = postcode
        self.house_number = house_number
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn
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
