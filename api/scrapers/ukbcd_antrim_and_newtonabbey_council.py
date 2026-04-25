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

    async def parse_data(self, page: str, **kwargs) -> dict:

        bindata = {"bins": []}

        soup = BeautifulSoup(page.content, "html.parser")
        soup.prettify

        collection_divs = soup.select("div.feature-box.bins")
        if not collection_divs:
            raise Exception("No collections found")

        for collection_div in collection_divs:
            date_p = collection_div.select_one("p.date")
            if not date_p:
                continue

            # Thu 22 Aug, 2024
            date_ = datetime.strptime(date_p.text.strip(), "%a %d %b, %Y").strftime(
                "%d/%m/%Y"
            )
            bins = collection_div.select("li")
            if not bins:
                continue
            for bin in bins:
                if not bin.text.strip():
                    continue
                bin_type = bin.text.strip()

                dict_data = {
                    "type": bin_type,
                    "collectionDate": date_,
                }
                bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Antrim and Newtownabbey"
URL = "https://antrimandnewtownabbey.gov.uk/residents/bins-recycling/bins-schedule/?Id=643"
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
