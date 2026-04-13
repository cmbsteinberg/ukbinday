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

    async def parse_data(self, page: str, **kwargs) -> dict:

        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)
        bindata = {"bins": []}

        URI = f"https://www.carmarthenshire.gov.wales/umbraco/Surface/SurfaceRecycling/Index/?uprn={user_uprn}&lang=en-GB"

        # Make the GET request
        response = await httpx.AsyncClient(follow_redirects=True).get(URI)

        # Parse the HTML
        soup = BeautifulSoup(response.content, "html.parser")

        # Find each bin collection container
        for container in soup.find_all(class_="bin-day-container"):
            # Get the bin type based on the class (e.g., Blue, Black, Garden, Nappy)
            bin_type = container.get("class")[1]  # Second class represents the bin type

            # Find the next collection date
            date_tag = container.find(class_="font11 text-center")
            if date_tag:
                collection_date = date_tag.text.strip()
            else:
                continue

            dict_data = {
                "type": bin_type,
                "collectionDate": datetime.strptime(
                    collection_date,
                    "%A %d/%m/%Y",
                ).strftime("%d/%m/%Y"),
            }
            bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Carmarthenshire"
URL = "https://www.carmarthenshire.gov.wales"
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
