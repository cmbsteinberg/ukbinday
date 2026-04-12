from __future__ import annotations
import re
from datetime import datetime
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
import httpx
from api.services.browser_pool import get as _get_browser_pool

def get_seasonal_overrides():
    url = 'https://www.barnet.gov.uk/recycling-and-waste/bin-collections/find-your-bin-collection-day'
    response = httpx.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        body_div = soup.find('div', class_='field--name-body')
        if body_div:
            ul_element = body_div.find('ul')
            if ul_element:
                li_elements = ul_element.find_all('li')
                overrides_dict = {}
                for li_element in li_elements:
                    li_text = li_element.text.strip()
                    li_text = re.sub('\\([^)]*\\)', '', li_text).strip()
                    if 'Collections for' in li_text and 'will be revised to' in li_text:
                        parts = li_text.split('will be revised to')
                        original_date = parts[0].replace('Collections for', '').replace('\xa0', ' ').strip()
                        revised_date = parts[1].strip()
                        date_parts = original_date.split()[1:]
                        if len(date_parts) == 2:
                            day, month = date_parts
                            day = day.zfill(2)
                            original_date = f'{original_date.split()[0]} {day} {month}'
                        overrides_dict[original_date] = revised_date
                return overrides_dict
    return {}

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
            user_paon = kwargs.get('paon')
            check_paon(user_paon)
            headless = kwargs.get('headless')
            web_driver = kwargs.get('web_driver')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            page_url = 'https://www.barnet.gov.uk/recycling-and-waste/bin-collections/find-your-bin-collection-day'
            await page.goto(page_url)
            try:
                accept_cookies_button = page.locator("xpath=//button[contains(text(), 'Accept additional cookies')]")
                await accept_cookies_button.evaluate('el => el.click()')
            except Exception as e:
                print(f'Cookie banner not found or clickable: {e}')
                pass
            find_your_collection_button = page.locator('text=Find your household collection day')
            await find_your_collection_button.evaluate('el => el.scrollIntoView()')
            await find_your_collection_button.evaluate('el => el.click()')
            try:
                accept_cookies = page.locator('#epdagree')
                await accept_cookies.evaluate('el => el.click()')
                accept_cookies_submit = page.locator('#epdsubmit')
                await accept_cookies_submit.evaluate('el => el.click()')
            except Exception as e:
                print(f'Second cookie banner not found or clickable: {e}')
                pass
            postcode_input = page.locator('[aria-label="Postcode"]')
            await postcode_input.fill(user_postcode)
            find_address_button = page.locator('[value="Find address"]')
            await find_address_button.evaluate('el => el.scrollIntoView()')
            await find_address_button.evaluate('el => el.click()')
            select_address_input = page.locator('#MainContent_CUSTOM_FIELD_808562d4b07f437ea751317cabd19d9eeaf8742f49cb4f7fa9bef99405b859f2')
            selected = False
            for addr_option in await select_address_input.locator('option').all():
                if not await addr_option.text_content() or await addr_option.text_content() == 'Please Select...':
                    continue
                option_text = (await addr_option.text_content()).upper()
                postcode_upper = user_postcode.upper()
                paon_str = str(user_paon).upper()
                if postcode_upper in option_text and (f', {paon_str},' in option_text or f', {paon_str} ' in option_text or f', {paon_str}A,' in option_text or option_text.endswith(f', {paon_str}')):
                    await select_address_input.select_option(value=await addr_option.get_attribute('value'))
                    selected = True
                    break
            if not selected:
                raise ValueError(f'Address not found for postcode {user_postcode} and house number {user_paon}')
            try:
                await page.locator("xpath=//div[contains(text(), 'Next collection') or contains(text(), 'collection date')]").wait_for()
            except:
                raise ValueError('Could not find bin collection data on the page')
            soup = BeautifulSoup(await page.content(), 'html.parser')
            try:
                overrides_dict = get_seasonal_overrides()
            except Exception as e:
                overrides_dict = {}
            bin_data = {'bins': []}
            collection_divs = soup.find_all('div', string=re.compile('Next collection date:'))
            if not collection_divs:
                collection_divs = []
                for div in soup.find_all('div'):
                    if div.get_text() and 'Next collection date:' in div.get_text():
                        collection_divs.append(div)
            for collection_div in collection_divs:
                try:
                    parent_div = collection_div.parent if collection_div.parent else collection_div
                    full_text = parent_div.get_text()
                    lines = full_text.split('\n')
                    bin_type = 'Unknown'
                    collection_date_string = ''
                    for i, line in enumerate(lines):
                        line = line.strip()
                        if 'Next collection date:' in line:
                            if i > 0:
                                bin_type = lines[i - 1].strip()
                            date_match = re.search('Next collection date:\\s+(.*)', line)
                            if date_match:
                                collection_date_string = date_match.group(1).strip().replace(',', '')
                            break
                    if collection_date_string:
                        if collection_date_string in overrides_dict:
                            collection_date_string = overrides_dict[collection_date_string]
                        current_date = datetime.now()
                        parsed_date = datetime.strptime(collection_date_string + f' {current_date.year}', '%A %d %B %Y')
                        if parsed_date.date() < current_date.date():
                            parsed_date = parsed_date.replace(year=current_date.year + 1)
                        formatted_date = parsed_date.strftime('%d/%m/%Y')
                        contains_date(formatted_date)
                        bin_info = {'type': bin_type, 'collectionDate': formatted_date}
                        bin_data['bins'].append(bin_info)
                except Exception as e:
                    pass
                    continue
            if not bin_data['bins']:
                print('No bin collection data found for this address')
                bin_data = {'bins': []}
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return bin_data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Barnet"
URL = "https://www.barnet.gov.uk/recycling-and-waste/bin-collections/find-your-bin-collection-day"
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
