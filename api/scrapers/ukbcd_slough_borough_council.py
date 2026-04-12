from __future__ import annotations
import re
from datetime import datetime
import httpx
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

def get_street_from_postcode(postcode: str, api_key: str) -> str:
    url = 'https://maps.googleapis.com/maps/api/geocode/json'
    params = {'address': postcode, 'key': api_key}
    response = httpx.get(url, params=params)
    data = response.json()
    if data['status'] != 'OK':
        raise ValueError(f"API error: {data['status']}")
    for component in data['results'][0]['address_components']:
        if 'route' in component['types']:
            return component['long_name']
    raise ValueError('No street (route) found in the response.')

class CouncilClass(AbstractGetBinDataClass):

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        bin_data = {'bins': []}
        try:
            user_postcode = kwargs.get('postcode')
            if not user_postcode:
                raise ValueError('No postcode provided.')
            check_postcode(user_postcode)
            headless = kwargs.get('headless')
            web_driver = kwargs.get('web_driver')
            UserAgent = 'Mozilla/5.0'
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            page_url = 'https://www.slough.gov.uk/bin-collections'
            await page.goto(page_url)
            await page.locator('#ccc-recommended-settings').click()
            address_input = page.locator('#keyword_directory30')
            user_address = get_street_from_postcode(user_postcode, 'AIzaSyBDLULT7EIlNtHerswPtfmL15Tt3Oc0bV8')
            await address_input.fill(user_address)
            await address_input.press('Enter')
            await page.locator('span.list__link-text').all()
            span_elements = await page.locator('span.list__link-text').all()
            for span in span_elements:
                if user_address.lower() in (await span.text_content()).lower():
                    await span.click()
                    break
            else:
                raise Exception(f'No link found containing address: {user_address}')
            await page.locator('section.site-content').wait_for()
            soup = BeautifulSoup(await page.content(), 'html.parser')
            for heading in soup.select('dt.definition__heading'):
                heading_text = heading.get_text(strip=True)
                if 'bin day details' in heading_text.lower():
                    bin_type = heading_text.split()[0].capitalize() + ' bin'
                    dd = heading.find_next_sibling('dd')
                    link = dd.find('a', href=True)
                    if link:
                        bin_url = link['href']
                        if not bin_url.startswith('http'):
                            bin_url = 'https://www.slough.gov.uk' + bin_url
                        await page.goto(bin_url)
                        await page.locator('div.page-content').wait_for()
                        child_soup = BeautifulSoup(await page.content(), 'html.parser')
                        editor_div = child_soup.find('div', class_='editor')
                        if not editor_div:
                            continue
                        ul = editor_div.find('ul')
                        if not ul:
                            continue
                    for li in ul.find_all('li'):
                        raw_text = li.get_text(strip=True).replace('.', '')
                        if 'no collection' in raw_text.lower() or 'no collections' in raw_text.lower():
                            continue
                        raw_date = raw_text
                        try:
                            parsed_date = datetime.strptime(raw_date, '%d %B %Y')
                        except ValueError:
                            raw_date_cleaned = raw_date.split('(')[0].strip()
                            try:
                                parsed_date = datetime.strptime(raw_date_cleaned, '%d %B %Y')
                            except Exception:
                                print(f'Could not parse date: {raw_text}')
                                continue
                        formatted_date = parsed_date.strftime('%d/%m/%Y')
                        contains_date(formatted_date)
                        bin_data['bins'].append({'type': bin_type, 'collectionDate': formatted_date})
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return bin_data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Slough"
URL = "https://www.slough.gov.uk/bin-collections"
TEST_CASES = {}


class Source:
    def __init__(self, postcode: str | None = None):
        self.postcode = postcode
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
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
