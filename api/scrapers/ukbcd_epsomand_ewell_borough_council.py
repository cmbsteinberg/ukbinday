from __future__ import annotations
import re
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
        user_uprn = kwargs.get('uprn')
        user_postcode = kwargs.get('postcode')
        check_uprn(user_uprn)
        bindata = {'bins': []}
        _ctx = None
        try:
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            portal_url = 'https://iportal.itouchvision.com/icollectionday/collection-day/?uuid=8E7DCC4BD90D8405D154BE053147018A8C0B5F09'
            await page.goto(portal_url)
            postcode_input = page.locator('#postcodeSearch')
            if user_postcode:
                postcode = user_postcode
            else:
                raise ValueError('Postcode is required for EpsomandEwellBoroughCouncil')
            await page.evaluate(f"\n                const input = document.getElementById('postcodeSearch');\n                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;\n                nativeInputValueSetter.call(input, '{postcode}');\n                input.dispatchEvent(new Event('input', {{ bubbles: true }}));\n                input.dispatchEvent(new Event('change', {{ bubbles: true }}));\n            ")
            find_button = page.locator('.govuk-button').first
            await find_button.click()
            address_select = page.locator('#addressSelect')
            await page.evaluate(f"\n                const select = document.getElementById('addressSelect');\n                select.value = '{user_uprn}';\n                select.dispatchEvent(new Event('change', {{ bubbles: true }}));\n            ")
            await page.locator('h3').wait_for()
            soup = BeautifulSoup(await page.content(), 'html.parser')
            h3_elements = soup.find_all('h3')
            for h3 in h3_elements:
                bin_type = h3.text.strip()
                if not bin_type:
                    continue
                next_elem = h3.find_next_sibling()
                if not next_elem:
                    continue
                date_text = next_elem.text.strip()
                try:
                    match = re.search('(\\w+)\\s+(\\d{1,2})\\s+(\\w+)', date_text)
                    if match:
                        day = match.group(2)
                        month = match.group(3)
                        current_date = datetime.now()
                        current_year = current_date.year
                        try:
                            date_obj = datetime.strptime(f'{day} {month} {current_year}', '%d %B %Y')
                            if (current_date - date_obj).days > 30:
                                date_obj = datetime.strptime(f'{day} {month} {current_year + 1}', '%d %B %Y')
                        except ValueError:
                            date_obj = datetime.strptime(f'{day} {month} {current_year + 1}', '%d %B %Y')
                        collection_date = date_obj.strftime(date_format)
                        dict_data = {'type': bin_type, 'collectionDate': collection_date}
                        bindata['bins'].append(dict_data)
                except Exception as e:
                    print(f"Error parsing date '{date_text}': {e}")
                    continue
            bindata['bins'].sort(key=lambda x: datetime.strptime(x.get('collectionDate'), '%d/%m/%Y'))
        finally:
            if _ctx:
                await _ctx.close()
        return bindata

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Epsom and Ewell"
URL = "https://www.epsom-ewell.gov.uk"
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
