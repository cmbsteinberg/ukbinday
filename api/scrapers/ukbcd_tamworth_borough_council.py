import re

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
        check_uprn(user_uprn)
        bindata = {"bins": []}

        def solve(s):
            return re.sub(r"(\d)(st|nd|rd|th)", r"\1", s)

        headers = {
            "Origin": "https://www.lichfielddc.gov.uk",
            "Referer": "https://www.lichfielddc.gov.uk",
            "User-Agent": "Mozilla/5.0",
        }

        # Tamworth waste services are operated by Lichfield District Council
        URI = f"https://www.lichfielddc.gov.uk/homepage/6/bin-collection-dates?uprn={user_uprn}"

        # Make the GET request
        response = await _http.get(URI, headers=headers)

        soup = BeautifulSoup(response.text, "html.parser")

        bins = soup.find_all("h3", class_="bin-collection-tasks__heading")
        dates = soup.find_all("p", class_="bin-collection-tasks__date")

        current_year = datetime.now().year
        current_month = datetime.now().month

        for i in range(len(dates)):
            bint = " ".join(bins[i].text.split()[2:4])
            date = dates[i].text

            date = datetime.strptime(
                solve(date),
                "%d %B",
            )

            if (current_month > 10) and (date.month < 3):
                date = date.replace(year=(current_year + 1))
            else:
                date = date.replace(year=current_year)

            dict_data = {
                "type": bint,
                "collectionDate": date.strftime("%d/%m/%Y"),
            }
            bindata["bins"].append(dict_data)

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Tamworth Borough"
URL = "https://www.tamworth.gov.uk"
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
