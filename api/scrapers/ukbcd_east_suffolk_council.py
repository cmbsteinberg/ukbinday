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
            await page.goto('https://my.eastsuffolk.gov.uk/service/Bin_collection_dates_finder')
            page.frame_locator('#fillform-frame-1')
            postcode = page.locator('#alt_postcode_search')
            await postcode.fill(user_postcode.replace(' ', ''))
            address = page.locator('#alt_choose_address')
            await page.locator('.spinner-outer').wait_for(state='hidden')
            sleep(2)
            await address.select_option(value=user_uprn)
            await page.locator('.spinner-outer').wait_for(state='hidden')
            sleep(2)
            data_table = page.locator('xpath=//div[@data-field-name="collection_details"]/div[contains(@class, "fieldContent")]/div[contains(@class, "repeatable-table-wrapper")]')
            soup = BeautifulSoup(await data_table.get_attribute('innerHTML'), features='html.parser')
            data = {'bins': []}
            rows = soup.find('table').find('tbody').find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                bin_type = await cols[2].find_all('span')[1].text.title()
                collection_date = cols[3].find_all('span')[1].text
                collection_date = datetime.strptime(collection_date, '%d/%m/%Y').strftime(date_format)
                dict_data = {'type': bin_type, 'collectionDate': collection_date}
                data['bins'].append(dict_data)
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

TITLE = "East Suffolk"
URL = "https://my.eastsuffolk.gov.uk/service/Bin_collection_dates_finder"
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
