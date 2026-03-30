import json
from datetime import datetime, timedelta

import httpx

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class CouncilClass(AbstractGetBinDataClass):
    def parse_data(self, page: str, **kwargs) -> dict:
        api_url = "http://lite.tameside.gov.uk/BinCollections/CollectionService.svc/GetBinCollection"
        uprn = kwargs.get("uprn")
        check_uprn(uprn)

        params = {
            "version": "3.1.4",
            "uprn": uprn,
            "token": "",
            "notification": "1",
            "operatingsystemid": "2",
            "testmode": "true",
        }

        headers = {"content-type": "text/plain"}

        pass  # urllib3 warnings disabled
        response = httpx.post(api_url, json=params, headers=headers)

        json_response = json.loads(response.content)["GetBinCollectionResult"]["Data"]

        today = datetime.today()
        eight_weeks = datetime.today() + timedelta(days=8 * 7)
        data = {"bins": []}
        collection_tuple = []

        bin_friendly_names = {
            "2": "Blue Bin",
            "6": "Green Bin",
            "5": "Black Bin",
            "3": "Brown Bin",
        }

        for item in json_response:
            collection_date = datetime.strptime(
                item.get("CollectionDate"), "%d/%m/%Y %H:%M:%S"
            )
            if today.date() <= collection_date.date() <= eight_weeks.date():
                bin_type = bin_friendly_names.get(item.get("BinType"))
                collection_tuple.append(
                    (bin_type, collection_date.strftime(date_format))
                )

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

TITLE = "Tameside"
URL = "http://lite.tameside.gov.uk/BinCollections/CollectionService.svc/GetBinCollection"
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
