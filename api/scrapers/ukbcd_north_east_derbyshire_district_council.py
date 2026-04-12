from __future__ import annotations
from datetime import datetime
from time import sleep
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
            page_url = 'https://myselfservice.ne-derbyshire.gov.uk/service/Check_your_Bin_Day'
            data = {'bins': []}
            user_uprn = kwargs.get('uprn')
            user_uprn = str(user_uprn).zfill(12)
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            check_uprn(user_uprn)
            check_postcode(user_postcode)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(page_url)
            iframe_presense = page.locator('#fillform-frame-1')
            
            frame = page.frame_locator('#fillform-frame-1')
            inputElement_postcodesearch = frame.locator('[name="postcode_search"]')
            await inputElement_postcodesearch.fill(str(user_postcode))
            dropdown = frame.locator('[name="selAddress"]')
            dropdown_options = frame.locator('.lookup-option')
            option_element = frame.locator(f'option.lookup-option[value="{str(user_uprn)}"]')
            await dropdown.select_option(value=str(user_uprn))
            h3_element = frame.locator("xpath=//th[contains(text(), 'Waste Collection')]")
            sleep(2)
            soup = BeautifulSoup(await page.content(), features='html.parser')
            print('Parsing HTML content...')
            collection_rows = soup.find_all('tr')
            bin_type_keywords = ['Black', 'Burgundy', 'Green']
            for row in collection_rows:
                cells = row.find_all('td')
                if len(cells) == 3:
                    date_labels = cells[0].find_all('label')
                    collection_date = None
                    for label in date_labels:
                        label_text = label.get_text().strip()
                        if contains_date(label_text):
                            collection_date = label_text
                            break
                    bin_label = cells[2].find('label')
                    bin_types = bin_label.get_text().strip() if bin_label else None
                    if collection_date and bin_types:
                        print(f'Found collection: {collection_date} - {bin_types}')
                        formatted_date = datetime.strptime(collection_date, '%d/%m/%Y').strftime(date_format)
                        for bin_keyword in bin_type_keywords:
                            if bin_keyword in bin_types:
                                data['bins'].append({'type': f'{bin_keyword} Bin', 'collectionDate': formatted_date})
            print(f"Found {len(data['bins'])} collections")
            print(f'Final data: {data}')
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "North East Derbyshire"
URL = "https://myselfservice.ne-derbyshire.gov.uk/service/Check_your_Bin_Day"
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
