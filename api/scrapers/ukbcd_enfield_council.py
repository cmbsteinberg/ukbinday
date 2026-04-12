from __future__ import annotations
from bs4 import BeautifulSoup
import pdb
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
            user_postcode = kwargs.get('postcode')
            if not user_postcode:
                raise ValueError('No postcode provided.')
            check_postcode(user_postcode)
            user_paon = kwargs.get('paon')
            check_paon(user_paon)
            headless = kwargs.get('headless')
            web_driver = kwargs.get('web_driver')
            user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'
            _ctx = await _get_browser_pool().new_context()
            page = await _ctx.new_page()
            await page.route('**/*', lambda route: route.abort() if route.request.resource_type in {'image', 'stylesheet', 'font', 'media'} else route.continue_())
            page_url = 'https://www.enfield.gov.uk/services/rubbish-and-recycling/find-my-collection-day'
            await page.goto(page_url)
            print('Waiting for page to load (Cloudflare check)...')
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    print(f'Page loaded: {await page.title()}')
                    break
                except:
                    print(f'Attempt {attempt + 1}: Timeout waiting for page load. Current title: {await page.title()}')
                    if attempt < max_attempts - 1:
                        await page.reload()
                    else:
                        print('Failed to bypass Cloudflare after multiple attempts')
            try:
                accept_cookies = page.locator('#ccc-notify-reject')
                await accept_cookies.click()
            except:
                print('Accept cookies banner not found or clickable within the specified time.')
                pass
            try:
                iframes = await page.locator('iframe').all()
                for i, iframe in enumerate(iframes):
                    try:
                        
                        frame = page.frame_locator(iframe)
                        inputs = await frame.locator('input').all()
                        for inp in inputs:
                            aria_label = await inp.get_attribute('aria-label') or ''
                            placeholder = await inp.get_attribute('placeholder') or ''
                            if 'address' in aria_label.lower() or 'postcode' in placeholder.lower():
                                break
                        else:
                            continue
                        break
                    except Exception as e:
                        continue
            except Exception as e:
                pass
            postcode_input = None
            selectors = ['[aria-label="Enter your address"]', 'input[placeholder*="postcode"]', 'input[placeholder*="address"]', 'input[type="text"]']
            for selector in selectors:
                try:
                    postcode_input = page.locator(selector)
                    break
                except:
                    continue
            if not postcode_input:
                raise ValueError('Could not find postcode input field')
            await postcode_input.fill(user_postcode)
            find_address_button = page.locator('#submitButton0')
            await find_address_button.click()
            select_address_input = page.locator('[aria-label="Select full address"]')
            first_option = (await select_address_input.locator('option').all())[0].accessible_name
            template_parts = first_option.split(', ')
            template_parts[0] = user_paon
            addr_label = ', '.join(template_parts)
            for addr_option in await select_address_input.locator('option').all():
                option_name = addr_option.accessible_name[0:len(addr_label)]
                if option_name == addr_label:
                    break
            await select_address_input.select_option(value=await addr_option.text_content())
            target_div_id = 'FinalResults'
            target_div = page.locator(f'#{target_div_id}')
            soup = BeautifulSoup(await page.content(), 'html.parser')
            target_div = soup.find('div', {'id': target_div_id})
            if target_div:
                bin_data = {'bins': []}
                for bin_div in target_div.find_all('div'):
                    try:
                        bin_collection_message = bin_div.find('p').text.strip()
                        date_pattern = '\\b\\d{2}/\\d{2}/\\d{4}\\b'
                        collection_date_string = re.search(date_pattern, bin_div.text).group(0).strip().replace(',', '')
                    except AttributeError:
                        continue
                    current_date = datetime.now()
                    parsed_date = datetime.strptime(collection_date_string, '%d/%m/%Y')
                    if parsed_date.date() < current_date.date():
                        parsed_date = parsed_date.replace(year=current_date.year + 1)
                    else:
                        parsed_date = parsed_date.replace(year=current_date.year)
                    formatted_date = parsed_date.strftime('%d/%m/%Y')
                    contains_date(formatted_date)
                    bin_type_match = re.search('Your next (.*?) collection', bin_collection_message)
                    if bin_type_match:
                        bin_info = {'type': bin_type_match.group(1), 'collectionDate': formatted_date}
                        bin_data['bins'].append(bin_info)
            else:
                raise ValueError('Collection data not found.')
        except Exception as e:
            print(f'An error occurred: {e}')
            raise
        finally:
            if _ctx:
                await _ctx.close()
        return bin_data

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Enfield"
URL = "https://www.enfield.gov.uk/services/rubbish-and-recycling/find-my-collection-day"
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
