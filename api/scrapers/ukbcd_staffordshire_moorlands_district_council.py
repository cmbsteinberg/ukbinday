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
        await page.goto('https://www.staffsmoorlands.gov.uk/findyourbinday')
        inputElement_postcode = page.locator('#FINDBINDAYSSTAFFORDSHIREMOORLANDS_POSTCODESELECT_POSTCODE')
        await inputElement_postcode.fill(user_postcode)
        findAddress = page.locator('#FINDBINDAYSSTAFFORDSHIREMOORLANDS_POSTCODESELECT_PAGE1NEXT_NEXT')
        await findAddress.click()
        dropdown = page.locator('#FINDBINDAYSSTAFFORDSHIREMOORLANDS_ADDRESSSELECT_ADDRESS')
        await dropdown.select_option(value=user_uprn)
        submit = page.locator('#FINDBINDAYSSTAFFORDSHIREMOORLANDS_ADDRESSSELECT_ADDRESSSELECTNEXTBTN_NEXT')
        await submit.click()
        await page.locator('.bin-collection__month').wait_for()
        soup = BeautifulSoup(await page.content(), features='html.parser')
        await _ctx.close()
        for month_wrapper in soup.find_all('div', {'class': 'bin-collection__month'}):
            if month_wrapper:
                month_year = month_wrapper.find('h3', {'class': 'bin-collection__title'}).get_text(strip=True)
                for collection in month_wrapper.find_all('li', {'class': 'bin-collection__item'}):
                    day = collection.find('span', {'class': 'bin-collection__number'}).get_text(strip=True)
                    if month_year and day:
                        bin_date = datetime.strptime(day + ' ' + month_year, '%d %B %Y')
                        dict_data = {'type': collection.find('span', {'class': 'bin-collection__type'}).get_text(strip=True), 'collectionDate': bin_date.strftime(date_format)}
                        data['bins'].append(dict_data)
        data['bins'].sort(key=lambda x: datetime.strptime(x.get('collectionDate'), '%d/%m/%Y'))
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Staffordshire Moorlands"
URL = "https://www.staffsmoorlands.gov.uk/"
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
