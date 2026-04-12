from __future__ import annotations
import datetime
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
            url = kwargs.get('url')
            user_paon = kwargs.get('paon')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_paon(user_paon)
            check_postcode(user_postcode)
            user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto('https://www.somerset.gov.uk/collection-days')
            inputElement_postcode = page.locator('#postcodeSearch')
            await inputElement_postcode.fill(user_postcode)
            findAddress = page.locator('.govuk-button')
            await findAddress.click()
            await page.locator(f"""xpath={"//select[@id='addressSelect']//option[contains(., '" + user_paon + "')]"}""").click()
            await page.locator("xpath=//h2[contains(@class,'mt-4') and contains(@class,'govuk-heading-s') and normalize-space(.)='Your next collections']").wait_for()
            soup = BeautifulSoup(await page.content(), features='html.parser')
            collections = soup.find_all('div', {'class': 'p-2'})
            for collection in collections:
                bin_type = collection.find('h3').get_text()
                next_collection = soup.find('div', {'class': 'fw-bold'}).get_text()
                following_collection = soup.find(lambda t: t.name == 'div' and t.get_text(strip=True).lower().startswith('followed by')).get_text()
                next_collection_date = datetime.strptime(next_collection, '%A %d %B')
                following_collection_date = datetime.strptime(following_collection, 'followed by %A %d %B')
                current_date = datetime.now()
                next_collection_date = next_collection_date.replace(year=current_date.year)
                following_collection_date = following_collection_date.replace(year=current_date.year)
                next_collection_date = get_next_occurrence_from_day_month(next_collection_date)
                following_collection_date = get_next_occurrence_from_day_month(following_collection_date)
                dict_data = {'type': bin_type, 'collectionDate': next_collection_date.strftime(date_format)}
                data['bins'].append(dict_data)
                dict_data = {'type': bin_type, 'collectionDate': following_collection_date.strftime(date_format)}
                data['bins'].append(dict_data)
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Somerset"
URL = "https://www.somerset.gov.uk/"
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
