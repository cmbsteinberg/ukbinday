from __future__ import annotations
import re
from datetime import datetime, timedelta
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
        _ctx = None
        try:
            page_url = 'https://community.cotswold.gov.uk/s/waste-collection-enquiry'
            data = {'bins': []}
            house_number = kwargs.get('paon')
            postcode = kwargs.get('postcode')
            full_address = house_number if house_number else f'{house_number}, {postcode}'
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(page_url)
            print('Waiting for Salesforce Lightning components to load...')
            try:
                await page.locator("xpath=//label[contains(text(), 'Enter your address')]").wait_for()
                print('Address label found')
            except Exception as e:
                print(f'Address label not found: {e}')
            try:
                address_entry_field = page.locator("xpath=//label[contains(text(), 'Enter your address')]/following-sibling::*//input").first
                print('Found address input field using label xpath')
            except Exception as e:
                print(f'Could not find address input field: {e}')
                raise Exception('Could not find address input field')
            try:
                await address_entry_field.fill('')
                await address_entry_field.fill(str(full_address))
                print(f'Entered address: {full_address}')
            except Exception as e:
                print(f'Error entering address: {e}')
                raise
            try:
                await address_entry_field.click()
                print('Clicked input field to trigger dropdown')
            except Exception as e:
                print(f'Error clicking input field: {e}')
            try:
                dropdown_option = page.locator("xpath=//li[@role='presentation']")
                await dropdown_option.click()
                print('Clicked dropdown option')
            except Exception as e:
                print(f'Error clicking dropdown option: {e}')
                raise
            try:
                next_button = page.locator("xpath=//button[contains(text(), 'Next')]")
                await next_button.click()
                print('Clicked Next button')
            except Exception as e:
                print(f'Error clicking Next button: {e}')
                raise
            try:
                await page.locator("xpath=//span[contains(text(), 'Collection Day')]").wait_for()
                print('Bin collection data table loaded')
            except Exception as e:
                print(f'Bin collection table not found: {e}')
            soup = BeautifulSoup(await page.content(), features='html.parser')
            current_year = datetime.now().year
            rows = []
            table_selectors = ['tr.slds-hint-parent', "tr[class*='slds']", 'table tr', '.slds-table tr', 'tbody tr']
            for selector in table_selectors:
                rows = soup.select(selector)
                if rows:
                    break
            if not rows:
                collection_elements = soup.find_all(text=re.compile('(bin|collection|waste|recycling)', re.I))
                if collection_elements:
                    for element in collection_elements[:10]:
                        parent = element.parent
                        if parent:
                            text = parent.get_text().strip()
                            if text and len(text) > 10:
                                date_patterns = re.findall('\\b\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4}\\b|\\b\\d{1,2}\\s+\\w+\\s+\\d{4}\\b', text)
                                if date_patterns:
                                    data['bins'].append({'type': 'General Collection', 'collectionDate': date_patterns[0]})
                                    break
            for row in rows:
                try:
                    columns = row.find_all(['td', 'th'])
                    if len(columns) >= 2:
                        container_type = 'Unknown'
                        collection_date = ''
                        th_element = row.find('th')
                        if th_element:
                            container_type = th_element.get_text().strip()
                        elif columns:
                            container_type = columns[0].get_text().strip()
                        for col in columns[1:] if th_element else columns[1:]:
                            col_text = col.get_text().strip()
                            if col_text:
                                if col_text.lower() == 'today':
                                    collection_date = datetime.now().strftime('%d/%m/%Y')
                                    break
                                elif col_text.lower() == 'tomorrow':
                                    collection_date = (datetime.now() + timedelta(days=1)).strftime('%d/%m/%Y')
                                    break
                                else:
                                    try:
                                        clean_text = re.sub('[^a-zA-Z0-9,\\s/-]', '', col_text).strip()
                                        date_formats = ['%a, %d %B', '%d %B %Y', '%d/%m/%Y', '%d-%m-%Y', '%B %d, %Y']
                                        for fmt in date_formats:
                                            try:
                                                parsed_date = datetime.strptime(clean_text, fmt)
                                                if fmt == '%a, %d %B':
                                                    if parsed_date.replace(year=current_year) < datetime.now():
                                                        parsed_date = parsed_date.replace(year=current_year + 1)
                                                    else:
                                                        parsed_date = parsed_date.replace(year=current_year)
                                                collection_date = parsed_date.strftime('%d/%m/%Y')
                                                break
                                            except ValueError:
                                                continue
                                        if collection_date:
                                            break
                                    except Exception:
                                        continue
                        if container_type and collection_date and (container_type.lower() != 'unknown'):
                            data['bins'].append({'type': container_type, 'collectionDate': collection_date})
                except Exception as e:
                    print(f'Error processing row: {e}')
                    continue
            if not data['bins']:
                print('No bin collection data found. Page source:')
                print((await page.content())[:1000])
        except Exception as e:
            print(f'An error occurred: {e}')
            print(f'Full address used: {full_address}')
            print(f'Page URL: {page_url}')
            if _ctx:
                print(f'Current page title: {await page.title()}')
                print(f'Current URL: {page.url}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Cotswold"
URL = "https://community.cotswold.gov.uk/s/waste-collection-enquiry"
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
