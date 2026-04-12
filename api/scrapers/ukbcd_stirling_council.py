from __future__ import annotations
from bs4 import BeautifulSoup
from dateutil.parser import parse
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        try:
            data = {'bins': []}
            user_paon = kwargs.get('paon')
            postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            url = kwargs.get('url')
            print(f'Starting parse_data with parameters: postcode={postcode}, paon={user_paon}')
            print(f'Creating webdriver with: web_driver={web_driver}, headless={headless}')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            print(f'Navigating to URL: {url}')
            await page.goto(url)
            print('Successfully loaded the page')
            try:
                cookie_button = page.locator('#ccc-recommended-settings')
                await cookie_button.click()
                print('Cookie banner clicked.')
            except TimeoutError:
                print('No cookie banner appeared or selector failed.')
            print('Looking for postcode input...')
            post_code_input = page.locator('#js-postcode-lookup-postcode')
            await post_code_input.fill('')
            await post_code_input.fill(postcode)
            print(f'Entered postcode: {postcode}')
            await page.locator(':focus').press('Tab')
            await page.locator(':focus').press('Enter')
            print('Pressed ENTER on Find')
            print('Waiting for address dropdown...')
            address_select = page.locator('.select__input')
            await address_select.select_option(label=user_paon)
            print('Address selected successfully')
            await page.locator(':focus').press('Tab')
            await page.locator(':focus').press('Tab')
            await page.locator(':focus').press('Enter')
            print('Pressed ENTER on Next button')
            print('Looking for schedule list...')
            schedule_list = page.locator('.schedule__list')
            print('Parsing page with BeautifulSoup...')
            soup = BeautifulSoup(await page.content(), features='html.parser')
            print('Looking for collection details in the page...')
            schedule_items = []
            selectors = ['li.schedule__item']
            for selector in selectors:
                items = soup.select(selector)
                if items:
                    print(f'Found {len(items)} items using selector: {selector}')
                    schedule_items = items
                    break
            print(f'\nProcessing {len(schedule_items)} schedule items...')
            for item in schedule_items:
                try:
                    title = item.find('h2', class_='schedule__title')
                    bin_type = title.text.strip()
                    summary = item.find('p', class_='schedule__summary')
                    summary_text = summary.get_text(strip=True)
                    print(f'Found summary text: {summary_text}')
                    date_text = None
                    for splitter in ['Then every', 'then every', 'Every']:
                        if splitter in summary_text:
                            date_text = summary_text.split(splitter)[0].strip()
                            break
                    if not date_text:
                        date_text = summary_text
                    print(f'Extracted date text: {date_text}')
                    cleaned_date_text = remove_ordinal_indicator_from_date_string(date_text)
                    parsed_date = parse(cleaned_date_text, fuzzy=True)
                    bin_date = parsed_date.strftime('%d/%m/%Y')
                    if bin_type and bin_date:
                        dict_data = {'type': bin_type, 'collectionDate': bin_date}
                        data['bins'].append(dict_data)
                        print(f'Successfully added collection: {dict_data}')
                except Exception as e:
                    print(f'Error processing item: {e}')
                    continue
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            print('Cleaning up webdriver...')
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Stirling"
URL = "https://www.stirling.gov.uk/bins-and-recycling/bin-collection-dates-search/"
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
