import json

import httpx
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
        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)

        data = {"bins": []}
        collections = []
        api_url = f"https://dac.telford.gov.uk/BinDayFinder/Find/PropertySearch?uprn={user_uprn}"

        response = httpx.get(api_url)
        if response.status_code != 200:
            raise ConnectionError("Could not get latest data!")

        json_data = json.loads(response.text.replace("\\", "")[1:-1])["bincollections"]
        for item in json_data:
            collection_date = datetime.strptime(
                remove_ordinal_indicator_from_date_string(item.get("nextDate")),
                "%A %d %B",
            )
            next_collection = collection_date.replace(year=datetime.now().year)
            if datetime.now().month == 12 and next_collection.month == 1:
                next_collection = next_collection + relativedelta(years=1)

            collections.append((item.get("name"), next_collection))

        ordered_data = sorted(collections, key=lambda x: x[1])
        for item in ordered_data:
            dict_data = {
                "type": item[0],
                "collectionDate": item[1].strftime(date_format),
            }
            data["bins"].append(dict_data)

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Telford and Wrekin"
URL = "https://dac.telford.gov.uk/bindayfinder/"
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
