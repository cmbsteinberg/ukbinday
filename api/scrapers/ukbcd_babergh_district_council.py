from __future__ import annotations
import datetime
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
        _ctx = None
        try:
            web_driver = kwargs.get('web_driver')
            headless = kwargs.get('headless')
            user_postcode = kwargs.get('postcode')
            if not user_postcode:
                raise ValueError('No postcode provided.')
            check_postcode(user_postcode)
            user_paon = kwargs.get('paon')
            if not user_paon:
                raise ValueError('No house name/number provided.')
            check_paon(user_paon)
            data = {'bins': []}
            url = 'https://www.babergh.gov.uk/check-your-collection-day'
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            await page.goto(url)
            await page.locator('[aria-label="Postcode"]').wait_for()
            postcode_input = page.locator('[aria-label="Postcode"]')
            await postcode_input.fill(user_postcode)
            find_address_button = page.locator('.lfr-btn-label')
            await find_address_button.evaluate('el => el.scrollIntoView()')
            await find_address_button.evaluate('el => el.click()')
            select_address_input = page.locator('select')
            selected = False
            for addr_option in await select_address_input.locator('option').all():
                if not await addr_option.text_content() or await addr_option.text_content() == 'Please Select...':
                    continue
                option_text = (await addr_option.text_content()).upper()
                postcode_upper = user_postcode.upper()
                paon_str = str(user_paon).upper()
                if postcode_upper in option_text and (f'{paon_str} ' in option_text or f', {paon_str},' in option_text or f', {paon_str} ' in option_text or (f', {paon_str}A,' in option_text) or option_text.endswith(f', {paon_str}')):
                    await select_address_input.select_option(value=await addr_option.get_attribute('value'))
                    selected = True
                    break
            if not selected:
                raise ValueError(f'Address not found for postcode {user_postcode} and house number {user_paon}')
            await page.locator('#collection-cards').wait_for()
            soup = BeautifulSoup(await page.content(), 'html.parser')
            collection_cards = soup.find('div', class_='collection-cards')
            if collection_cards:
                cards = collection_cards.find_all('div', class_='card')
                for card in cards:
                    collection_type = card.find('h3').get_text()
                    p_tags = card.find_all('p')
                    for p_tag in p_tags:
                        if p_tag.get_text().startswith('Frequency'):
                            continue
                        date_str = p_tag.get_text().split(':')[1]
                        collection_date = datetime.strptime(date_str, '%a %d %b %Y')
                        dict_data = {'type': collection_type, 'collectionDate': collection_date.strftime(date_format)}
                        data['bins'].append(dict_data)
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Babergh"
URL = "https://www.babergh.gov.uk"
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
