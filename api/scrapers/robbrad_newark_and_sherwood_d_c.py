from datetime import timedelta

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

        URI = f"https://app.newark-sherwooddc.gov.uk/bincollection/calendar?pid={user_uprn}"

        # Make the GET request
        response = httpx.get(URI)
        # Get page with BS4
        soup = BeautifulSoup(response.text, features="html.parser")
        soup.prettify()

        # Work out some date bounds
        today = datetime.today()
        eight_weeks = datetime.today() + timedelta(days=8 * 7)
        data = {"bins": []}

        # Each month calendar is a table, so get the object then find all rows in that object.
        # Month and year is also a row and not included in the date, so save it then remove the row
        for month in soup.select('table[class*="table table-condensed"]'):
            info = month.find_all("tr")
            month_year = info[0].text.strip()

            info.pop(0)
            # Each remaining item is a bin collection, so get the type and tidy up the date.
            for item in info:
                bin_type = item.text.split(",")[0].strip()
                bin_date = datetime.strptime(
                    remove_ordinal_indicator_from_date_string(
                        item.text.split(",")[1].strip() + " " + month_year
                    ),
                    "%A %d %B %Y",
                )
                # Only include dates on or after today, but also only within eight weeks
                if (
                    today.date() <= bin_date.date() <= eight_weeks.date()
                    and "cancelled" not in bin_type
                ):
                    dict_data = {
                        "type": bin_type,
                        "collectionDate": bin_date.strftime(date_format),
                    }
                    data["bins"].append(dict_data)

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Newark and Sherwood"
URL = "https://app.newark-sherwooddc.gov.uk/bincollection/"
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
