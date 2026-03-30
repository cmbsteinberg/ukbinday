from datetime import timedelta

from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

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
        data = {"bins": []}

        # response = httpx.get('https://www.rochford.gov.uk/online-bin-collections-calendar', headers=headers)
        soup = BeautifulSoup(page.text, features="html.parser")
        soup.prettify()
        year = soup.find_all("table", {"class": "responsive-enabled govuk-table"})

        current_month = datetime.now().strftime("%B %Y")
        next_month = (datetime.now() + relativedelta(months=1, day=1)).strftime("%B %Y")

        for month in year:
            heading = (
                month.find("th", {"class": "govuk-table__header"}).get_text().strip()
            )
            if heading == current_month or heading == next_month:
                for week in month.find("tbody").find_all(
                    "tr", {"class": "govuk-table__row"}
                ):
                    week_text = week.get_text().strip().split("\n")
                    date_str = week_text[0].split(" - ")[0].split("–")[0].strip()
                    collection_date = datetime.strptime(
                        remove_ordinal_indicator_from_date_string(date_str),
                        "%A %d %B",
                    )
                    next_collection = collection_date.replace(year=datetime.now().year)
                    if datetime.now().month == 12 and next_collection.month == 1:
                        next_collection = next_collection + relativedelta(years=1)
                    bin_type = (
                        week_text[1]
                        .replace("collection week", "bin")
                        .strip()
                        .capitalize()
                    )
                    if next_collection.date() >= (datetime.now().date() - timedelta(6)):
                        dict_data = {
                            "type": bin_type,
                            "collectionDate": next_collection.strftime(date_format),
                        }
                        data["bins"].append(dict_data)
            else:
                continue

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Rochford"
URL = "https://www.rochford.gov.uk/online-bin-collections-calendar"
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
