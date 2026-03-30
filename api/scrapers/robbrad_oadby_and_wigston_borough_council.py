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

        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)
        bindata = {"bins": []}

        URI = f"https://my.oadby-wigston.gov.uk/location?put=ow{user_uprn}&rememberme=0&redirect=%2F"

        # Make the GET request
        response = httpx.get(URI)

        soup = BeautifulSoup(response.text, features="html.parser")
        soup.prettify()

        # Find the collection list
        collection_list = soup.find("ul", class_="refuse")

        current_year = datetime.now().year
        next_year = current_year + 1

        # Loop through each collection item
        for li in collection_list.find_all("li"):
            date_text = li.find("strong", class_="date").text.strip()
            bin_type = li.find("a").text  # Get the class for bin type

            # Parse the date
            if date_text == "Today":
                collection_date = datetime.now()
            else:
                try:
                    collection_date = datetime.strptime(date_text, "%A %d %b")
                except:
                    continue

            if (datetime.now().month == 12) and (collection_date.month == 1):
                collection_date = collection_date.replace(year=next_year)
            else:
                collection_date = collection_date.replace(year=current_year)

            dict_data = {
                "type": bin_type,
                "collectionDate": collection_date.strftime(date_format),
            }
            bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Oadby and Wigston"
URL = "https://my.oadby-wigston.gov.uk"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None):
        self.uprn = uprn
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn

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
