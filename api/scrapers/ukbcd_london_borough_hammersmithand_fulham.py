from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


# import the wonderful Beautiful Soup and the URL grabber
class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:

        user_postcode = kwargs.get("postcode")
        check_postcode(user_postcode)
        bindata = {"bins": []}

        user_postcode = user_postcode.strip().replace(" ", "")

        URI = f"https://www.lbhf.gov.uk/bin-recycling-day/results?postcode={user_postcode}"
        UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
        session = httpx.Client(follow_redirects=True)
        session.headers.update({"User-Agent": UA})
        # Make the GET request
        response = session.get(URI)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, features="html.parser")
        results = soup.find("div", {"class": "nearest-search-results"})
        ol = results.find("ol")
        bin_collections = ol.find_all("a")

        today = datetime.now().strftime("%A")

        for bin_collection in bin_collections:
            collection_day = bin_collection.get_text().split(" - ")[0]
            collection_type = bin_collection.get_text().split(" - ")[1]

            if days_of_week.get(collection_day) == days_of_week.get(today):
                collection_day = datetime.now().strftime(date_format)
            else:
                collection_day = get_next_day_of_week(collection_day)

            dict_data = {
                "type": collection_type,
                "collectionDate": collection_day,
            }
            bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Hammersmith & Fulham"
URL = "https://www.lbhf.gov.uk/"
TEST_CASES = {}


class Source:
    def __init__(self, postcode: str | None = None):
        self.postcode = postcode
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        kwargs = {}
        if self.postcode: kwargs['postcode'] = self.postcode

        def _run():
            page = ""
            if hasattr(self._scraper, "parse_data"):
                return self._scraper.parse_data(page, **kwargs)
            raise NotImplementedError("Could not find parse_data on scraper")

        data = await asyncio.to_thread(_run)

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
