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
            user_uprn = kwargs.get('uprn')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            url = kwargs.get('url')
            check_postcode(user_postcode)
            print(f'Starting parse_data with parameters: postcode={user_postcode}, uprn={user_uprn}')
            print(f'Creating webdriver with: web_driver={web_driver}, headless={headless}')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            print(f'Navigating to URL: {url}')
            await page.goto('https://www.torbay.gov.uk/recycling/bin-collections/')
            print('Successfully loaded the page')
            try:
                cookie_button = page.locator('xpath=/html/body/div[1]/div/div[2]/button[1]')
                await cookie_button.click()
                print('Cookie banner clicked.')
            except TimeoutError:
                print('No cookie banner appeared or selector failed.')
            bin_collection_button = page.locator('xpath=/html/body/main/div[4]/div/div[1]/div/div/div/div/div[2]/div/div/div/p/a')
            await bin_collection_button.click()
            original_window = page
            for window_handle in _ctx.pages:
                if window_handle != original_window:
                    await window_handle.bring_to_front()
                    break
            print('Looking for postcode input...')
            await page.locator('#FF1168-text').wait_for()
            post_code_input = page.locator('#FF1168-text')
            await post_code_input.fill('')
            await post_code_input.fill(user_postcode)
            print(f'Entered postcode: {user_postcode}')
            await post_code_input.press('Tab')
            await post_code_input.press('Enter')
            print('Pressed ENTER on Search button')
            address_select = page.locator('#FF1168-list')
            await address_select.click()
            options = await address_select.locator('option').all()
            print(f'Found {len(options)} options in dropdown')
            print('\nAvailable options:')
            for opt in options:
                value = await opt.get_attribute('value')
                text = await opt.text_content()
                print(f"Value: '{value}', Text: '{text}'")
            target_uprn = f'U{user_uprn}|'
            print(f'\nLooking for UPRN pattern: {target_uprn}')
            found = False
            for option in options:
                value = await option.get_attribute('value')
                if value and target_uprn in value:
                    print(f'Found matching address with value: {value}')
                    await option.click()
                    found = True
                    break
            if not found:
                print(f'No matching address found for UPRN: {user_uprn}')
                return data
            print('Address selected successfully')
            print('Waiting for address selection confirmation...')
            await page.locator('.esbAddressSelected').wait_for()
            print('Address selection confirmed')
            print('Clicking Submit button...')
            submit_button = page.locator('#submit-button')
            await submit_button.click()
            print('Waiting for collection details to load...')
            try:
                schedule_list = page.locator('#resiCollectionDetails')
                print('Collection details loaded successfully')
            except TimeoutError:
                print('Timeout waiting for collection details - checking if page needs refresh')
                await page.reload()
                schedule_list = page.locator('#resiCollectionDetails')
                print('Collection details loaded after refresh')
            print('Parsing page with BeautifulSoup...')
            soup = BeautifulSoup(await page.content(), features='html.parser')
            print('Looking for collection details in the page...')
            collection_rows = soup.select('#resiCollectionDetails .row.fs-4')
            print(f'\nProcessing {len(collection_rows)} collection rows...')
            for row in collection_rows:
                try:
                    service_type = row.select_one('div.col:nth-child(3)').text.strip()
                    date_text = row.select_one("div[style*='width:360px']").text.strip()
                    parsed_date = parse(date_text, fuzzy=True)
                    bin_date = parsed_date.strftime('%d/%m/%Y')
                    bin_type = service_type.replace(' Collection Service', '')
                    if bin_type and bin_date:
                        dict_data = {'type': bin_type, 'collectionDate': bin_date}
                        data['bins'].append(dict_data)
                        print(f'Successfully added collection: {dict_data}')
                except Exception as e:
                    print(f'Error processing collection row: {e}')
                    continue
            print('\nFinal bin collection data:')
            print(data)
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

TITLE = "Torbay"
URL = "https://www.torbay.gov.uk/recycling/bin-collections/"
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
