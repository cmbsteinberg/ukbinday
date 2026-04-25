import httpx
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.compat import httpx_helpers as _http


# import the wonderful Beautiful Soup and the URL grabber
class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page: str, **kwargs) -> dict:
        user_uprn = kwargs.get("uprn")
        print(f"Using UPRN: {user_uprn}")  # Debug
        bindata = {"bins": []}

        user_uprn = user_uprn.zfill(8)

        url = f"https://bindayfinder.moray.gov.uk/disp_bins.php?id={user_uprn}"

        # year = datetime.today().year
        # url = f"https://bindayfinder.moray.gov.uk/cal_{year}_view.php"
        print(f"Trying URL: {url}")  # Debug

        response = await _http.get(url)
        print(f"Response status code: {response.status_code}")  # Debug

        # if response.status_code != 200:
        #     fallback_url = "https://bindayfinder.moray.gov.uk/cal_2024_view.php"
        #     print(f"Falling back to: {fallback_url}")  # Debug
        #     response = await _http.get(
        #         fallback_url,
        #         params={"id": user_uprn},
        #     )
        #     print(f"Fallback response status: {response.status_code}")  # Debug

        soup = BeautifulSoup(response.text, "html.parser")

        # Find all container_images divs
        container_images = soup.find_all("div", class_="container_images")
        print(f"Found {len(container_images)} container images")  # Debug

        for container in container_images:
            # Get bin type from image alt text
            img = container.find("img")
            if img and img.get("alt"):
                # Use the full alt text as one bin type instead of splitting
                bin_type = img["alt"]
                print(f"Found bin type: {bin_type}")  # Debug

            # Get collection date from binz_txt
            date_text = container.find("div", class_="binz_txt")
            if date_text:
                date_str = date_text.text
                print(f"Found date text: {date_str}")  # Debug

                # Extract just the date portion
                import re

                date_match = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", date_str)
                if date_match:
                    date_portion = date_match.group(1)
                    try:
                        # Convert the date string to the required format
                        parsed_date = datetime.strptime(date_portion, "%d %B %Y")
                        collection_date = parsed_date.strftime("%d/%m/%Y")
                        print(f"Parsed date: {collection_date}")  # Debug

                        dict_data = {
                            "type": bin_type,
                            "collectionDate": collection_date,
                        }
                        bindata["bins"].append(dict_data)
                    except ValueError as e:
                        print(f"Error parsing date: {e}")  # Debug
                        continue

        print(f"Final bindata: {bindata}")  # Debug
        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Moray"
URL = "https://bindayfinder.moray.gov.uk/"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None):
        self.uprn = uprn
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn

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
