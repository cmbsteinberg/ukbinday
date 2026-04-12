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
            page_url = 'https://gloucester-self.achieveservice.com/service/Bins___Check_your_bin_day'
            bin_data = {'bins': []}
            user_uprn = kwargs.get('uprn')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_uprn(user_uprn)
            check_postcode(user_postcode)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(page_url)
            cookies_button = page.locator('#close-cookie-message')
            await cookies_button.click()
            iframe_presense = page.locator('#fillform-frame-1')
            
            frame = page.frame_locator('#fillform-frame-1')
            inputElement_postcodesearch = frame.locator('[name="find_postcode"]')
            await inputElement_postcodesearch.fill(user_postcode)
            dropdown = frame.locator('[name="chooseAddress"]')
            await dropdown.select_option(value=str(user_uprn))
            frame.locator('span[data-name=html1]')
            soup = BeautifulSoup(await page.content(), features='html.parser')

            def is_a_collection_date(t):
                return any(('Next collection' in c for c in t.children))
            for next_collection in soup.find_all(is_a_collection_date):
                bin_info = list(next_collection.parent.select_one('div:nth-child(1)').children)
                if not bin_info:
                    continue
                bin = bin_info[0].get_text()
                date = next_collection.select_one('strong').get_text(strip=True)
                bin_date = datetime.strptime(date, '%d %b %Y')
                dict_data = {'type': bin, 'collectionDate': bin_date.strftime(date_format)}
                bin_data['bins'].append(dict_data)
            bin_data['bins'].sort(key=lambda x: datetime.strptime(x.get('collectionDate'), date_format))
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return bin_data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Gloucester"
URL = "https://gloucester-self.achieveservice.com/service/Bins___Check_your_bin_day"
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
