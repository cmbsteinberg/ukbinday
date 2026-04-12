from __future__ import annotations
from datetime import datetime
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
import re
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
            page_url = 'https://community.fdean.gov.uk/s/waste-collection-enquiry'
            data = {'bins': []}
            house_number = kwargs.get('paon')
            postcode = kwargs.get('postcode')
            full_address = f'{house_number}, {postcode}'
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(page_url)
            address_entry_field = page.locator('xpath=//*[@placeholder="Search Properties..."]')
            await address_entry_field.fill(str(full_address))
            address_entry_field = page.locator(f'xpath=//*[@title="{full_address}"]')
            await address_entry_field.click()
            next_button = page.locator("xpath=//lightning-button/button[contains(text(), 'Next')]")
            await next_button.click()
            result = page.locator('xpath=//table[@class="slds-table slds-table_header-fixed slds-table_bordered slds-table_edit slds-table_resizable-cols"]')
            soup = BeautifulSoup(await result.get_attribute('innerHTML'), features='html.parser')
            data = {'bins': []}
            today = datetime.now()
            current_year = today.year
            rows = soup.find_all('tr', class_='slds-hint-parent')
            for row in rows:
                try:
                    bin_type_cell = row.find('th')
                    date_cell = row.find('td')
                    if not bin_type_cell or not date_cell:
                        continue
                    container_type = bin_type_cell.get('data-cell-value', '').strip()
                    raw_date_text = date_cell.get('data-cell-value', '').strip()
                    if 'today' in raw_date_text.lower():
                        parsed_date = today
                    elif 'tomorrow' in raw_date_text.lower():
                        parsed_date = today + timedelta(days=1)
                    else:
                        cleaned_date = re.sub('[^\\w\\s,]', '', raw_date_text)
                        try:
                            parsed_date = datetime.strptime(cleaned_date, '%a, %d %B')
                            parsed_date = parsed_date.replace(year=current_year)
                            if parsed_date < today:
                                parsed_date = parsed_date.replace(year=current_year + 1)
                        except Exception as e:
                            print(f"Could not parse date '{cleaned_date}': {e}")
                            continue
                    formatted_date = parsed_date.strftime(date_format)
                    data['bins'].append({'type': container_type, 'collectionDate': formatted_date})
                except Exception as e:
                    print(f'Error processing row: {e}')
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Forest of Dean"
URL = "https://community.fdean.gov.uk/s/waste-collection-enquiry"
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
