from __future__ import annotations
import re
from datetime import datetime
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import check_postcode, check_uprn, date_format
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):
    """
    Tendring District Council scraper.

    Fix: select the 'Next collection' column (not 'Previous Collection'), and
    handle cookie banner / iframe flow robustly.
    """

    async def parse_data(self, page_url: str, **kwargs) -> dict:
        """
        Scrape Tendring District Council's rubbish and recycling collection days for a given address and return upcoming collections.
        
        This navigates the council's canonical service page, enters the supplied postcode, selects the address by UPRN, parses the resulting waste collection table, and returns a list of future collection entries. Entries with collection dates on or before today are excluded.
        
        Parameters:
            page (str): Ignored; the method always uses the canonical Tendring service URL.
            uprn (int | str, via kwargs["uprn"]): Unique Property Reference Number used to select the address.
            postcode (str, via kwargs["postcode"]): Postcode to populate the address search field.
            web_driver (optional, via kwargs["web_driver"]): Selenium driver configuration or remote endpoint; if omitted a local driver is created.
            headless (bool, via kwargs["headless"]): Whether to run the browser headlessly; defaults to True when not provided.
        
        Returns:
            dict: {"bins": [{"type": <string>, "collectionDate": <string>}, ...]} where each entry describes a waste type and its upcoming collection date. `collectionDate` is formatted using the module's configured `date_format`.
        """
        _ctx = None
        bin_data: dict[str, list[dict]] = {'bins': []}
        try:
            page_url = 'https://tendring-self.achieveservice.com/en/service/Rubbish_and_recycling_collection_days'
            user_uprn = kwargs.get('uprn')
            user_postcode = kwargs.get('postcode')
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            if headless is None:
                headless = True
            check_uprn(user_uprn)
            check_postcode(user_postcode)
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(page_url)
            try:
                cookies_button = page.locator('#close-cookie-message')
                await cookies_button.click()
            except TimeoutError:
                pass
            without_login_button = page.locator('text=or, continue without an account')
            await without_login_button.click()
            iframe = page.locator('#fillform-frame-1')
            
            frame = page.frame_locator('#fillform-frame-1')
            input_postcode = frame.locator('[name="postcode_search"]')
            await input_postcode.fill('')
            await input_postcode.fill(user_postcode)
            dropdown = frame.locator('[name="selectAddress"]')
            await dropdown.select_option(value=str(user_uprn))
            await frame.locator('.wasteTable').wait_for()
            soup = BeautifulSoup(await page.content(), 'html.parser')
            table = soup.find('table', {'class': 'wasteTable'})
            if not table:
                return bin_data
            headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
            next_idx = None
            for i, h in enumerate(headers):
                if 'next' in h and 'collect' in h:
                    next_idx = i
                    break
            if next_idx is None:
                next_idx = 2
            type_idx = 0
            for i, h in enumerate(headers):
                if 'waste' in h and 'type' in h:
                    type_idx = i
                    break
            today = datetime.today().date()
            rows = (table.find('tbody') or table).find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if not cols or len(cols) <= max(type_idx, next_idx):
                    continue
                bin_type = re.sub('\\([^)]*\\)', '', cols[type_idx].get_text(strip=True))
                cell_txt = cols[next_idx].get_text(' ', strip=True)
                m = re.search('\\b(\\d{2}/\\d{2}/\\d{4})\\b', cell_txt)
                if not m:
                    continue
                date_str = m.group(1)
                try:
                    parsed = datetime.strptime(date_str, '%d/%m/%Y')
                except ValueError:
                    continue
                if parsed.date() <= today:
                    continue
                bin_data['bins'].append({'type': bin_type, 'collectionDate': parsed.strftime(date_format)})
            bin_data['bins'].sort(key=lambda x: datetime.strptime(x['collectionDate'], '%d/%m/%Y'))
            return bin_data
        finally:
            if _ctx:
                await _ctx.close()

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Tendring"
URL = "https://tendring-self.achieveservice.com/en/service/Rubbish_and_recycling_collection_days"
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
