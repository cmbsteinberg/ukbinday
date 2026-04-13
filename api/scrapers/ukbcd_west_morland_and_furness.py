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

        URI = f"https://www.westmorlandandfurness.gov.uk/bins-recycling-and-street-cleaning/waste-collection-schedule/view/{user_uprn}"

        headers = {
            "user-agent": "Mozilla/5.0",
        }

        current_year = datetime.now().year
        current_month = datetime.now().month

        response = await httpx.AsyncClient(follow_redirects=True).get(URI)

        soup = BeautifulSoup(response.text, "html.parser")
        # Extract links to collection shedule pages and iterate through the pages
        schedule = soup.findAll("div", {"class": "waste-collection__month"})
        for month in schedule:
            collectionmonth = datetime.strptime(month.find("h3").text, "%B")
            collectionmonth = collectionmonth.month
            collectiondays = month.findAll("li", {"class": "waste-collection__day"})
            for collectionday in collectiondays:
                day = collectionday.find(
                    "span", {"class": "waste-collection__day--day"}
                ).text.strip()
                collectiondate = datetime.strptime(day, "%d")
                collectiondate = collectiondate.replace(month=collectionmonth)
                bintype = collectionday.find(
                    "span", {"class": "waste-collection__day--colour"}
                ).text

                if (current_month > 9) and (collectiondate.month < 4):
                    collectiondate = collectiondate.replace(year=(current_year + 1))
                else:
                    collectiondate = collectiondate.replace(year=current_year)

                dict_data = {
                    "type": bintype,
                    "collectionDate": collectiondate.strftime("%d/%m/%Y"),
                }
                bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Westmorland and Furness"
URL = "https://www.westmorlandandfurness.gov.uk/"
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
