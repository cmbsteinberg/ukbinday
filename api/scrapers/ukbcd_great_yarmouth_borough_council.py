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
        _ctx = None
        try:
            user_uprn = kwargs.get('uprn')
            user_postcode = kwargs.get('postcode')
            headless = kwargs.get('headless')
            web_driver = kwargs.get('web_driver')
            url = kwargs.get('url')
            check_uprn(user_uprn)
            check_postcode(user_postcode)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(url)
            accept_cookies_button = page.locator('[name="acceptall"]')
            await accept_cookies_button.click()
            postcode_input = page.locator('#WASTECOLLECTIONCALENDARV2_ADDRESS_ALSF')
            await postcode_input.fill(user_postcode)
            await postcode_input.press('Tab')
            await postcode_input.press('Enter')
            select_address_input = page.locator('#WASTECOLLECTIONCALENDARV2_ADDRESS_ALML')
            await select_address_input.click()
            await select_address_input.select_option(value=user_uprn)
            await select_address_input.click()
            await select_address_input.press('Tab')
            await select_address_input.press('Tab')
            await select_address_input.press('Enter')
            target_div = page.locator('#WASTECOLLECTIONCALENDARV2_LOOKUP_SHOWSCHEDULE')
            soup = BeautifulSoup(await page.content(), 'html.parser')
            bin_data = {'bins': []}
            next_collections = {}
            bin_types = {'bulky': 'Bulky Collection', 'green': 'Recycling', 'black': 'General Waste', 'brown': 'Garden Waste'}
            for div in soup.select('.collection-area'):
                img = div.select_one('img')
                detail = div.select_one('.collection-detail')
                date_text = detail.select_one('b').get_text(strip=True)
                try:
                    date_obj = datetime.strptime(date_text + ' 2025', '%A %d %B %Y')
                    if date_obj.date() < datetime.today().date():
                        continue
                except ValueError:
                    continue
                description = detail.get_text(separator=' ', strip=True).lower()
                alt_text = img['alt'].lower()
                for key, name in bin_types.items():
                    if key in alt_text or key in description:
                        formatted_date = date_obj.strftime('%d/%m/%Y')
                        bin_entry = {'type': name, 'collectionDate': formatted_date}
                        if name not in next_collections or date_obj < datetime.strptime(next_collections[name]['collectionDate'], '%d/%m/%Y'):
                            next_collections[name] = bin_entry
                            print(f'Found next collection for {name}: {formatted_date}')
                        break
            bin_data['bins'] = list(next_collections.values())
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        print('\nFinal bin data:')
        print(bin_data)
        return bin_data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Great Yarmouth"
URL = "https://myaccount.great-yarmouth.gov.uk/article/6456/Find-my-waste-collection-days"
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
