from __future__ import annotations
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
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
            user_paon = user_paon.upper()
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto('https://en.powys.gov.uk/binday')
            accept_button = page.locator('[name="acceptall"]')
            await accept_button.click()
            inputElement_postcode = page.locator('#BINDAYLOOKUP_ADDRESSLOOKUP_ADDRESSLOOKUPPOSTCODE')
            await inputElement_postcode.fill(user_postcode)
            findAddress = page.locator('#BINDAYLOOKUP_ADDRESSLOOKUP_ADDRESSLOOKUPSEARCH')
            await findAddress.click()
            await page.locator(f"""xpath={"//select[@id='BINDAYLOOKUP_ADDRESSLOOKUP_ADDRESSLOOKUPADDRESS']//option[contains(., '" + user_paon + "')]"}""").click()
            await page.locator('#BINDAYLOOKUP_ADDRESSLOOKUP_ADDRESSLOOKUPBUTTONS_NEXT').click()
            await page.locator('#BINDAYLOOKUP_COLLECTIONDATES_COLLECTIONDATES').wait_for()
            soup = BeautifulSoup(await page.content(), features='html.parser')
            general_rubbish_section = soup.find('div', class_='bdl-card bdl-card--refuse')
            general_rubbish_dates = [li.text for li in general_rubbish_section.find_next('ul').find_all('li')]
            for date in general_rubbish_dates:
                dict_data = {'type': 'General Rubbish / Wheelie bin', 'collectionDate': datetime.strptime(remove_ordinal_indicator_from_date_string(date.split(' (')[0]), '%A %d %B %Y').strftime(date_format)}
                data['bins'].append(dict_data)
            recycling_section = soup.find('div', class_='bdl-card bdl-card--recycling')
            recycling_dates = [li.text for li in recycling_section.find_next('ul').find_all('li')]
            for date in recycling_dates:
                dict_data = {'type': 'Recycling and Food Waste', 'collectionDate': datetime.strptime(remove_ordinal_indicator_from_date_string(date.split(' (')[0]), '%A %d %B %Y').strftime(date_format)}
                data['bins'].append(dict_data)
            garden_waste_section = soup.find('div', class_='bdl-card bdl-card--garden')
            garden_waste_dates = [li.text for li in garden_waste_section.find_next('ul').find_all('li')]
            for date in garden_waste_dates:
                try:
                    dict_data = {'type': 'Garden Waste', 'collectionDate': datetime.strptime(remove_ordinal_indicator_from_date_string(date.split(' (')[0]), '%A %d %B %Y').strftime(date_format)}
                    data['bins'].append(dict_data)
                except:
                    continue
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Powys"
URL = "https://www.powys.gov.uk"
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
