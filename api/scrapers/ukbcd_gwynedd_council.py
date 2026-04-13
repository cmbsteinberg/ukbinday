import httpx
from bs4 import BeautifulSoup, Tag

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


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

        URI = f"https://diogel.gwynedd.llyw.cymru/Daearyddol/en/LleDwinByw/Index/{user_uprn}"

        # Make the GET request
        response = await httpx.AsyncClient(follow_redirects=True).get(URI)

        soup = BeautifulSoup(response.text, "html.parser")
        collections_headline = soup.find("h6", text="Next collection dates:")
        if not isinstance(collections_headline, Tag):
            raise Exception("Could not find collections")
        collections = collections_headline.find_next("ul").find_all("li")

        for collection in collections:
            if not isinstance(collection, Tag):
                continue
            for p in collection.find_all("p"):
                p.extract()

            bin_type, date_str = collection.text.strip().split(":")[:2]
            bin_type, date_str = bin_type.strip(), date_str.strip()

            dict_data = {
                "type": bin_type,
                "collectionDate": datetime.strptime(date_str, "%A %d/%m/%Y").strftime(
                    date_format
                ),
            }
            bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Gwynedd"
URL = "https://diogel.gwynedd.llyw.cymru"
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
