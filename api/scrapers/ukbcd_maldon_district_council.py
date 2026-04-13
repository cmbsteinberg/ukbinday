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
        data = {"bins": []}
        uprn = kwargs.get("uprn")
        check_uprn(uprn)

        pass  # urllib3 warnings disabled
        response = await httpx.AsyncClient(follow_redirects=True).get(
            f"https://maldon.suez.co.uk/maldon/ServiceSummary?uprn={uprn}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64)"},
        )
        if response.status_code != 200:
            raise ValueError("No bin data found for provided UPRN.")

        soup = BeautifulSoup(response.text, features="html.parser")
        collections = soup.find_all("div", {"class": "panel"})
        for c in collections:
            binType = c.find("div", {"class": "panel-heading"}).get_text(strip=True)
            collectionDate = ""
            rows = c.find("div", {"class": "panel-body"}).find_all(
                "div", {"class": "row"}
            )
            for row in rows:
                if row.find("strong").get_text(strip=True).lower() == "next collection":
                    collectionDate = row.find("div", {"class": "col-sm-9"}).get_text(
                        strip=True
                    )

            if collectionDate != "":
                collection_data = {
                    "type": binType,
                    "collectionDate": collectionDate,
                }
                data["bins"].append(collection_data)

        data["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Maldon"
URL = "https://maldon.suez.co.uk/maldon/ServiceSummary"
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
