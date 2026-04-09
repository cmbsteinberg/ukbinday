import json
from datetime import datetime

import httpx

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
        api_url = (
            "https://waste-api.york.gov.uk/api/Collections/GetBinCollectionDataForUprn/"
        )
        uprn = kwargs.get("uprn")
        check_uprn(uprn)

        pass  # urllib3 warnings disabled
        response = httpx.get(f"{api_url}{uprn}")
        json_response = json.loads(response.content)["services"]
        data = {"bins": []}
        collection_tuple = []

        for item in json_response:
            collection_date = datetime.strptime(
                item.get("nextCollection"), "%Y-%m-%dT%H:%M:%S"
            ).strftime(date_format)
            collection_tuple.append((item.get("service"), collection_date))

        ordered_data = sorted(collection_tuple, key=lambda x: x[1])

        for item in ordered_data:
            dict_data = {
                "type": item[0],
                "collectionDate": item[1],
            }
            data["bins"].append(dict_data)

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "York"
URL = "https://waste-api.york.gov.uk/api/Collections/GetBinCollectionDataForUprn/"
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
