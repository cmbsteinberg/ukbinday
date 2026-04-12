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
            user_postcode = kwargs.get('postcode')
            if not user_postcode:
                raise ValueError('No postcode provided.')
            check_postcode(user_postcode)
            user_uprn = kwargs.get('uprn')
            headless = kwargs.get('headless')
            web_driver = kwargs.get('web_driver')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            page_url = 'https://iapp.itouchvision.com/iappcollectionday/collection-day/?uuid=FEBA68993831481FD81B2E605364D00A8DC017A4'
            await page.goto(page_url)
            postcode_input = page.locator('#postcodeSearch')
            await postcode_input.fill(user_postcode)
            await postcode_input.press('Tab')
            await postcode_input.press('Enter')
            select_address_input = page.locator('xpath=//*[@id="addressSelect"]')
            if not user_uprn:
                raise ValueError('No UPRN provided')
            try:
                await select_address_input.select_option(value=str(user_uprn))
            except Exception as e:
                raise ValueError(f'Could not find address with UPRN: {user_uprn}')
            await page.locator('div.ant-row.d-flex.justify-content-between').wait_for()
            await page.locator('div.ant-col h3.text-white').all()
            soup = BeautifulSoup(await page.content(), 'html.parser')
            bin_data = {'bins': []}
            bin_divs = soup.find_all('div', class_='ant-col')
            for bin_div in bin_divs:
                bin_type_elem = bin_div.find('h3', class_='text-white')
                if not bin_type_elem:
                    continue
                bin_type = bin_type_elem.text.strip()
                date_elem = bin_div.find('div', class_='text-white fw-bold')
                if not date_elem:
                    continue
                collection_date_string = date_elem.text.strip()
                current_date = datetime.now()
                try:
                    parsed_date = datetime.strptime(collection_date_string + f' {current_date.year}', '%A %d %B %Y')
                    if parsed_date.date() < current_date.date():
                        parsed_date = parsed_date.replace(year=current_date.year + 1)
                    formatted_date = parsed_date.strftime('%d/%m/%Y')
                    contains_date(formatted_date)
                    bin_info = {'type': bin_type, 'collectionDate': formatted_date}
                    bin_data['bins'].append(bin_info)
                except ValueError as e:
                    print(f'Error parsing date {collection_date_string}: {e}')
                    continue
            if not bin_data['bins']:
                raise ValueError('No collection data found')
            print(bin_data)
            return bin_data
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Hyndburn"
URL = "https://iapp.itouchvision.com/iappcollectionday/collection-day/?uuid=FEBA68993831481FD81B2E605364D00A8DC017A4"
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
