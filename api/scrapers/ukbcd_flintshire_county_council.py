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

        URI = f"https://digital.flintshire.gov.uk/FCC_BinDay/Home/Details2/{user_uprn}"

        # Make the GET request
        response = httpx.get(URI)

        # Parse the HTML content
        soup = BeautifulSoup(response.content, "html.parser")

        # Adjust these tags and classes based on actual structure
        # Example for finding collection dates and types
        bin_collections = soup.find_all(
            "div", class_="col-md-12 col-lg-12 col-sm-12 col-xs-12"
        )  # Replace with actual class name

        # Extracting and printing the schedule data
        schedule = []
        for collection in bin_collections:
            dates = collection.find_all("div", class_="col-lg-2 col-md-2 col-sm-2")
            bin_type = collection.find("div", class_="col-lg-3 col-md-3 col-sm-3")

            if dates[0].text.strip() == "Date of Collection":
                continue

            bin_types = bin_type.text.strip().split(" / ")
            date = dates[0].text.strip()

            # Loop through the dates for each collection type
            for bin_type in bin_types:

                dict_data = {
                    "type": bin_type,
                    "collectionDate": date,
                }
                bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )
        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Flintshire"
URL = "https://digital.flintshire.gov.uk"
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
