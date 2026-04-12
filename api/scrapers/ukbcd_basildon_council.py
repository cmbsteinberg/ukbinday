from __future__ import annotations
import httpx
import json
from datetime import datetime
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import check_uprn, date_format as DATE_FORMAT
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete class that implements the abstract bin data fetching and parsing logic.
    """

    async def parse_data(self, page: str, **kwargs) -> dict:
        uprn = kwargs.get('uprn')
        check_uprn(uprn)
        try:
            return self._try_api_method(uprn)
        except Exception:
            return await self._try_selenium_method(uprn, **kwargs)

    def _try_api_method(self, uprn: str) -> dict:
        url_base = 'https://basildonportal.azurewebsites.net/api/getPropertyRefuseInformation'
        payload = {'uprn': uprn}
        headers = {'Content-Type': 'application/json'}
        response = httpx.post(url_base, data=json.dumps(payload), headers=headers)
        if response.status_code != 200:
            raise Exception(f'API failed with status {response.status_code}')
        data = response.json()
        bins = []
        available_services = data.get('refuse', {}).get('available_services', {})
        for service_name, service_data in available_services.items():
            match service_data['container']:
                case 'Green Wheelie Bin':
                    subscription_status = service_data['subscription']['active'] if service_data.get('subscription') else False
                    type_descr = f"Green Wheelie Bin ({('Active' if subscription_status else 'Expired')})"
                case 'N/A':
                    type_descr = service_data.get('name', 'Unknown Service')
                case _:
                    type_descr = service_data.get('container', 'Unknown Container')
            date_str = service_data.get('current_collection_date')
            if date_str:
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    formatted_date = date_obj.strftime(DATE_FORMAT)
                    bins.append({'type': type_descr, 'collectionDate': formatted_date})
                except ValueError:
                    pass
        return {'bins': bins}

    async def _try_selenium_method(self, uprn: str, **kwargs) -> dict:
        _ctx = await _get_browser_pool().new_context()
        page = await _ctx.new_page()
        await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
        if not _ctx:
            raise Exception('Selenium driver required for new portal')
        await page.goto('https://mybasildon.powerappsportals.com/check/where_i_live/')
        postcode_input = page.locator("input[type='text']")
        await postcode_input.fill('SS14 1EY')
        submit_btn = page.locator("button[type='submit'], input[type='submit']").first
        await submit_btn.click()
        await page.locator('.collection-info, .bin-info').wait_for()
        bins = []
        collection_elements = await page.locator('.collection-info, .bin-info').all()
        for element in collection_elements:
            bin_type = await element.locator('.bin-type').first.text_content()
            collection_date = await element.locator('.collection-date').first.text_content()
            bins.append({'type': bin_type, 'collectionDate': collection_date})
        return {'bins': bins}

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Basildon"
URL = "https://mybasildon.powerappsportals.com/check/where_i_live/"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None):
        self.uprn = uprn
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn

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
