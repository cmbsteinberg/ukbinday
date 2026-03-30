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
        # Make a BS4 object
        soup = BeautifulSoup(page.text, features="html.parser")
        soup.prettify()

        # Form a JSON wrapper
        data = {"bins": []}

        # Search for the specific table using BS4
        rows = soup.find("table", {"class": re.compile("table")}).find_all("tr")

        # Loops the Rows
        for row in rows:
            cells = row.find_all(
                "td", {"class": lambda L: L and L.startswith("service-name")}
            )

            if len(cells) > 0:
                collectionDatesRawData = row.find_all(
                    "td", {"class": lambda L: L and L.startswith("next-service")}
                )[0].get_text(strip=True)
                collectionDate = collectionDatesRawData[
                    16 : len(collectionDatesRawData)
                ].split(",")
                bin_type = row.find_all(
                    "td", {"class": lambda L: L and L.startswith("service-name")}
                )[0].h4.get_text(strip=True)

                for collectDate in collectionDate:
                    # Make each Bin element in the JSON
                    dict_data = {
                        "type": bin_type,
                        "collectionDate": datetime.strptime(
                            collectDate.strip(), "%d %b %Y"
                        ).strftime(date_format),
                    }

                    # Add data to the main JSON Wrapper
                    data["bins"].append(dict_data)

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Sheffield"
URL = "https://wasteservices.sheffield.gov.uk/property/100050931898"
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
