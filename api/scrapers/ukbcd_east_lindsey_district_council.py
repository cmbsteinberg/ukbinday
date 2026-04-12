from __future__ import annotations
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
            data = {'bins': []}
            user_paon = kwargs.get('paon')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_paon(user_paon)
            check_postcode(user_postcode)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto('https://www.e-lindsey.gov.uk/mywastecollections')
            inputElement_postcode = page.locator('#WASTECOLLECTIONDAYS202526_LOOKUP_ADDRESSLOOKUPPOSTCODE')
            await inputElement_postcode.fill(user_postcode)
            findAddress = page.locator('#WASTECOLLECTIONDAYS202526_LOOKUP_ADDRESSLOOKUPSEARCH')
            await findAddress.click()
            await page.locator(f"""xpath={"//select[@id='WASTECOLLECTIONDAYS202526_LOOKUP_ADDRESSLOOKUPADDRESS']//option[contains(., '" + user_paon + "')]"}""").click()
            submit = page.locator('#WASTECOLLECTIONDAYS202526_LOOKUP_FIELD2_NEXT')
            await submit.click()
            await page.locator('.waste-results').wait_for()
            soup = BeautifulSoup(await page.content(), features='html.parser')
            for collection in soup.find_all('div', {'class': 'waste-result'}):
                collection_date = None
                for p_tag in collection.find_all('p'):
                    if 'next collection is' in p_tag.text:
                        collection_date = p_tag.find('strong').text
                        break
                if collection_date:
                    dict_data = {'type': collection.find('h3').get_text(strip=True), 'collectionDate': datetime.strptime(remove_ordinal_indicator_from_date_string(collection_date), '%A %d %B %Y').strftime(date_format)}
                    data['bins'].append(dict_data)
            data['bins'].sort(key=lambda x: datetime.strptime(x.get('collectionDate'), '%d/%m/%Y'))
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "East Lindsey"
URL = "https://www.e-lindsey.gov.uk/"
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
