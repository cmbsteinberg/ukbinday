# Eastbourne uses the same script.

from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
import httpx


# import the wonderful Beautiful Soup and the URL grabber
class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page: str, **kwargs) -> dict:

        try:
            user_uprn = kwargs.get("uprn")
            check_uprn(user_uprn)
            url = f"https://environmentfirst.co.uk/house.php?uprn={user_uprn}"
            if not user_uprn:
                # This is a fallback for if the user stored a URL in old system. Ensures backwards compatibility.
                url = kwargs.get("url")
        except Exception as e:
            raise ValueError(f"Error getting identifier: {str(e)}")

        # Make a BS4 object
        page = await httpx.AsyncClient(follow_redirects=True).get(url)
        soup = BeautifulSoup(page.text, features="html.parser")
        soup.prettify()

        # Get the paragraph lines from the page
        data = {"bins": []}
        page_text = soup.find("div", {"class": "collect"}).find_all("p")

        # Parse the correct lines (find them, remove the ordinal indicator and make them the correct format date) and
        # then add them to the dictionary
        rubbish_day = datetime.strptime(
            remove_ordinal_indicator_from_date_string(
                page_text[2].find_next("strong").text
            ),
            "%d %B %Y",
        ).strftime(date_format)
        dict_data = {
            "type": "Rubbish",
            "collectionDate": rubbish_day,
        }
        data["bins"].append(dict_data)
        recycling_day = datetime.strptime(
            remove_ordinal_indicator_from_date_string(
                page_text[4].find_next("strong").text
            ),
            "%d %B %Y",
        ).strftime(date_format)
        dict_data = {
            "type": "Recycling",
            "collectionDate": recycling_day,
        }
        data["bins"].append(dict_data)

        if len(page_text) > 5:
            garden_day = datetime.strptime(
                remove_ordinal_indicator_from_date_string(
                    page_text[6].find_next("strong").text
                ),
                "%d %B %Y",
            ).strftime(date_format)
            dict_data = {
                "type": "Garden",
                "collectionDate": garden_day,
            }
            data["bins"].append(dict_data)

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Lewes"
URL = "https://www.lewes-eastbourne.gov.uk/article/1158/When-is-my-bin-collection-day"
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
