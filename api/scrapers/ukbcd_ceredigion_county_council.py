from __future__ import annotations
from time import sleep
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the base
    class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        _ctx = None
        try:
            house_number = kwargs.get('paon')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_paon(house_number)
            check_postcode(user_postcode)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto('https://www.ceredigion.gov.uk/resident/bins-recycling/')
            try:
                accept_cookies = page.locator("xpath=//button[@id='ccc-reject-settings']")
                await accept_cookies.click()
            except:
                print('Accept cookies banner not found or clickable within the specified time.')
                pass
            postcode_search = page.locator("xpath=//a[contains(text(), 'Postcode Search')]")
            await postcode_search.evaluate('el => el.scrollIntoView(true)')
            sleep(2)
            await postcode_search.click()
            postcode_entry_box = page.locator("xpath=//input[@data-ebv-desc='Postcode']")
            await postcode_entry_box.fill(user_postcode)
            postcode_button = page.locator("xpath=//input[@value='Find Address']")
            await postcode_button.click()
            address_dropdown = page.locator("xpath=//select[@data-ebv-desc='Select Address']")
            await address_dropdown.select_option(label=house_number)
            address_next_button = page.locator("xpath=//input[@value='Next']")
            await address_next_button.click()
            result = page.locator("xpath=//form[contains(., 'Next collection:')]")
            soup = BeautifulSoup(await result.get_attribute('innerHTML'), features='html.parser')
            data = {'bins': []}
            collection_panels = soup.find_all('div', class_='eb-OL2RoeVH-panel')
            for panel in collection_panels:
                try:
                    next_text = panel.find_all('span')[-1].text.strip()
                    match = re.search('Next collection:\\s*(\\w+day)\\s+(\\d{1,2})(?:st|nd|rd|th)?\\s+(\\w+)', next_text)
                    if not match:
                        continue
                    _, day, month = match.groups()
                    year = datetime.now().year
                    full_date = f'{day} {month} {year}'
                    collection_date = datetime.strptime(full_date, '%d %B %Y').strftime(date_format)
                    bin_image_blocks = panel.find_next_siblings('div', class_='waste_image')
                    for block in bin_image_blocks:
                        label = block.find('span')
                        if label:
                            bin_type = label.text.strip()
                            dict_data = {'type': bin_type, 'collectionDate': collection_date}
                            data['bins'].append(dict_data)
                except Exception as e:
                    print(f'Skipping one panel due to: {e}')
            data['bins'].sort(key=lambda x: datetime.strptime(x.get('collectionDate'), date_format))
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Ceredigion"
URL = "https://www.ceredigion.gov.uk/resident/bins-recycling/"
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
