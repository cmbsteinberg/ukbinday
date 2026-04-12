from __future__ import annotations
from datetime import datetime
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
        """
        Retrieve bin collection dates for a property from Halton Council's waste service.
        
        This method loads the council's waste service page, submits the provided property identifier and postcode, parses the resulting collection schedule, and returns structured bin collection entries.
        
        Parameters:
            paon (str, via kwargs): Property identifier — house number or property name.
            postcode (str, via kwargs): Property postcode.
            web_driver (str or selenium.webdriver, via kwargs): Optional webdriver backend identifier or instance passed to create_webdriver.
            headless (bool, via kwargs): If True, the browser is created in headless mode.
        
        Returns:
            dict: A dictionary with a single key "bins" containing a list of collection entries. Each entry is a dict with:
                - "type" (str): Waste type name (capitalized).
                - "collectionDate" (str): Collection date formatted as "DD/MM/YYYY".
        """
        _ctx = None
        try:
            data = {'bins': []}
            user_paon = kwargs.get('paon')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            page_url = f'https://webapp.halton.gov.uk/PublicWebForms/WasteServiceSearchv1.aspx'
            user_agent = 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)'
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(page_url)
            inputElement_property = page.locator('[name="ctl00$ContentPlaceHolder1$txtProperty"]')
            await inputElement_property.fill(user_paon)
            inputElement_postcodesearch = page.locator('[name="ctl00$ContentPlaceHolder1$txtPostcode"]')
            await inputElement_postcodesearch.fill(user_postcode)
            page.frame_locator("iframe[name^='a-'][src^='https://www.google.com/recaptcha/api2/anchor?']")
            await page.locator("xpath=//span[@id='recaptcha-anchor']").press('Enter')
            search_btn = page.locator('xpath=//*[@id="ContentPlaceHolder1_btnSearch"]')
            await search_btn.press('Enter')
            await page.locator('#collectionTabs').wait_for()
            soup = BeautifulSoup(await page.content(), features='html.parser')
            anchor_elements = soup.select('#collectionTabs a.ui-tabs-anchor')
            for anchor in anchor_elements:
                waste_type = anchor.text.strip()
                panel_id = anchor.get('href')
                panel = soup.select_one(panel_id)
                ul_elements = panel.find_all('ul')
                if len(ul_elements) >= 2:
                    second_ul = ul_elements[1]
                    li_elements = second_ul.find_all('li')
                    date_texts = [re.sub('[^a-zA-Z0-9,\\s]', '', li.get_text(strip=True)).strip() for li in li_elements]
                    for date_text in date_texts:
                        date_string_without_ordinal = re.sub('(\\d+)(st|nd|rd|th)', '\\1', date_text)
                        parsed_date = datetime.strptime(date_string_without_ordinal, '%A %d %B %Y')
                        formatted_date = parsed_date.strftime('%d/%m/%Y')
                        data['bins'].append({'type': waste_type.capitalize(), 'collectionDate': formatted_date})
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Halton"
URL = "https://webapp.halton.gov.uk/PublicWebForms/WasteServiceSearchv1.aspx#collections"
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
