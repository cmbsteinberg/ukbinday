from __future__ import annotations
import json
from datetime import datetime, timedelta
from typing import Any, Dict
from bs4 import BeautifulSoup
from dateutil.parser import parse
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool
DAYS_OF_WEEK = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6}

async def get_bank_holiday_changes(page) -> Dict[str, str]:
    """Fetch and parse bank holiday collection changes from the council website."""
    bank_holiday_url = 'https://www.hillingdon.gov.uk/bank-holiday-collections'
    changes: Dict[str, str] = {}
    try:
        await page.goto(bank_holiday_url)
        if '404' in await page.title() or 'Page not found' in await page.content():
            print('Bank holiday page not found (404).')
            return changes
        try:
            await page.locator('table').wait_for()
        except TimeoutError:
            print('No tables found on the bank holiday page.')
            return changes
        soup = BeautifulSoup(await page.content(), features='html.parser')
        tables = soup.find_all('table')
        if not tables:
            print('No relevant tables found on the bank holiday page.')
            return changes
        for table in tables:
            headers = [th.text.strip() for th in table.find_all('th')]
            if 'Normal collection day' in headers and 'Revised collection day' in headers:
                for row in table.find_all('tr')[1:]:
                    cols = row.find_all('td')
                    if len(cols) >= 2:
                        normal_date = cols[0].text.strip()
                        revised_date = cols[1].text.strip()
                        try:
                            normal_date = parse(normal_date, fuzzy=True).strftime('%d/%m/%Y')
                            revised_date = parse(revised_date, fuzzy=True).strftime('%d/%m/%Y')
                            changes[normal_date] = revised_date
                        except Exception as e:
                            print(f'Error parsing dates: {e}')
                            continue
    except Exception as e:
        print(f'An error occurred while fetching bank holiday changes: {e}')
    return changes

class CouncilClass(AbstractGetBinDataClass):

    async def parse_data(self, page_url: str, **kwargs: Any) -> Dict[str, Any]:
        _ctx = None
        try:
            data: Dict[str, Any] = {'bins': []}
            user_paon = kwargs.get('paon')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            url = kwargs.get('url')
            check_paon(user_paon)
            check_postcode(user_postcode)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(url)
            try:
                cookie_button = page.locator('button.btn.btn--cookiemessage.btn--cancel.btn--contrast')
                await cookie_button.click()
            except TimeoutError:
                pass
            post_code_input = page.locator('#WASTECOLLECTIONDAYLOOKUPINCLUDEGARDEN_ADDRESSLOOKUPPOSTCODE')
            await post_code_input.fill('')
            await post_code_input.fill(user_postcode)
            await post_code_input.press('Tab')
            await post_code_input.press('Enter')
            try:
                address_select = page.locator('#WASTECOLLECTIONDAYLOOKUPINCLUDEGARDEN_ADDRESSLOOKUPADDRESS')
                options = (await address_select.locator('option').all())[1:]
                if not options:
                    raise Exception(f'No addresses found for postcode: {user_postcode}')
                normalized_user_input = ''.join((c for c in user_paon if c.isalnum())).lower()
                for option in options:
                    normalized_option = ''.join((c for c in await option.text_content() if c.isalnum())).lower()
                    if normalized_user_input in normalized_option:
                        await option.click()
                        break
            except TimeoutError:
                raise Exception('Timeout waiting for address options to populate')
            await page.locator('#WASTECOLLECTIONDAYLOOKUPINCLUDEGARDEN_COLLECTIONTABLE').wait_for()
            soup = BeautifulSoup(await page.content(), features='html.parser')
            table = soup.find('div', id='WASTECOLLECTIONDAYLOOKUPINCLUDEGARDEN_COLLECTIONTABLE').find('table')
            collection_day_text = table.find_all('tr')[2].find_all('td')[1].text.strip()
            day_of_week = next((day for day in DAYS_OF_WEEK if day.lower() in collection_day_text.lower()), None)
            if not day_of_week:
                raise Exception(f"Could not determine collection day from text: '{collection_day_text}'")
            today = datetime.now()
            days_ahead = (DAYS_OF_WEEK[day_of_week] - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            next_collection = today + timedelta(days=days_ahead)
            bin_types = ['General Waste', 'Recycling', 'Food Waste']
            for bin_type in bin_types:
                data['bins'].append({'type': bin_type, 'collectionDate': next_collection.strftime('%d/%m/%Y')})
            bin_rows = soup.select('div.bin--row:not(:first-child)')
            for row in bin_rows:
                try:
                    bin_type = row.select_one('div.col-md-3').text.strip()
                    collection_dates_div = row.select('div.col-md-3')[1]
                    next_collection_text = ''.join(collection_dates_div.find_all(text=True, recursive=False)).strip()
                    cleaned_date_text = remove_ordinal_indicator_from_date_string(next_collection_text)
                    parsed_date = parse(cleaned_date_text, fuzzy=True)
                    bin_date = parsed_date.strftime('%d/%m/%Y')
                    if bin_type and bin_date:
                        data['bins'].append({'type': bin_type, 'collectionDate': bin_date})
                except Exception as e:
                    print(f'Error processing item: {e}')
                    continue
            print('\nChecking for bank holiday collection changes...')
            bank_holiday_changes = await get_bank_holiday_changes(page)
            for bin_data in data['bins']:
                original_date = bin_data['collectionDate']
                if original_date in bank_holiday_changes:
                    new_date = bank_holiday_changes[original_date]
                    print(f"Bank holiday change: {bin_data['type']} collection moved from {original_date} to {new_date}")
                    bin_data['collectionDate'] = new_date
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        print('\nFinal data dictionary:')
        print(json.dumps(data, indent=2))
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Hillingdon"
URL = "https://www.hillingdon.gov.uk/collection-day"
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
