import httpx
from dateutil import parser

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class CouncilClass(AbstractGetBinDataClass):
    def parse_data(self, page: str, **kwargs) -> dict:
        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)

        data = {"bins": []}

        headers = {
            "Content-Type": "application/json; charset=UTF-8",
        }

        req_data = {"uprn": user_uprn, "noticeBoard": "default"}

        url = "https://gis.stalbans.gov.uk/NoticeBoard9/VeoliaProxy.NoticeBoard.asmx/GetServicesByUprnAndNoticeBoard"

        response = httpx.post(url, json=req_data, headers=headers)

        collections_response = response.json()

        collections = []

        for collection in collections_response["d"]:
            collection_data = collection["ServiceHeaders"][0]
            bin_type = collection_data["TaskType"]
            collection_date = collection_data["Next"]
            next_collection = parser.isoparser().isoparse(collection_date)
            collections.append((bin_type, next_collection))

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

TITLE = "St Albans"
URL = "https://gis.stalbans.gov.uk/NoticeBoard9/VeoliaProxy.NoticeBoard.asmx/GetServicesByUprnAndNoticeBoard"
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
