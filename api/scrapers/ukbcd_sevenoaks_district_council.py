from __future__ import annotations
from typing import Any
from dateutil.parser import parse
from api.compat.ukbcd.common import date_format
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):

    def wait_for_element_conditions(self, page, conditions, timeout: int=5):
        try:
            pass
        except TimeoutError:
            print('Timed out waiting for page to load')
            raise

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        try:
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            page_url = 'https://sevenoaks-dc-host01.oncreate.app/w/webpage/waste-collection-day'
            user_postcode = kwargs.get('postcode')
            user_paon = kwargs.get('paon')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(page_url)
            postcode_css_selector = '#address_search_postcode'
            postcode_input_box = page.locator(postcode_css_selector).first
            await postcode_input_box.fill(user_postcode)
            await postcode_input_box.press('Enter')
            select_address_dropdown = page.locator('xpath=//select')
            if user_paon is not None:
                for option in await select_address_dropdown.locator('option').all():
                    if user_paon in await option.text_content():
                        await select_address_dropdown.select_option(label=await option.text_content())
                        break
            else:
                await select_address_dropdown.select_option(index=1)
            response_xpath_selector = '//div[@data-class_name]//h4/../../../..'
            elements = await page.locator(f'xpath={response_xpath_selector}').all()
            data = {'bins': []}
            for element in elements:
                try:
                    raw_bin_name = await element.locator('h4').first.text_content()
                    raw_next_collection_date = (await element.locator('xpath=.//div[input]').all())[1].text
                    if 'suspended' in raw_next_collection_date.lower() or 'restarting' in raw_next_collection_date.lower():
                        continue
                    parsed_bin_date = parse(raw_next_collection_date, fuzzy_with_tokens=True)[0]
                    dict_data = {'type': raw_bin_name, 'collectionDate': parsed_bin_date.strftime(date_format)}
                    data['bins'].append(dict_data)
                except (IndexError, TimeoutError):
                    print('Error finding element for bin')
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Sevenoaks"
URL = "https://sevenoaks-dc-host01.oncreate.app/w/webpage/waste-collection-day"
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
