import time

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

        user_postcode = kwargs.get("postcode")
        user_paon = kwargs.get("paon")
        check_postcode(user_postcode)
        check_paon(user_paon)
        bindata = {"bins": []}

        URI = "https://api.eu.recollect.net/api/areas/RedcarandClevelandUK/services/50006/address-suggest"

        params = {
            "q": user_postcode,
            "locale": "en-GB",
            "_": str(int(time.time() * 1000)),
        }

        # print(params)

        # Send GET request
        response = httpx.get(URI, params=params)

        addresses = response.json()

        place_id = next(
            (
                item["place_id"]
                for item in addresses
                if item.get("name", "").startswith(user_paon)
            ),
            addresses[1]["place_id"] if addresses[1] else None,
        )

        # print(addresses)
        # print(f"PlaceID - {place_id}")

        URI = (
            f"https://api.eu.recollect.net/api/places/{place_id}/services/50006/events"
        )

        after = datetime.today()
        before = after + timedelta(days=30)

        after = after.strftime("%Y-%m-%d")
        before = before.strftime("%Y-%m-%d")

        # print(after)
        # print(before)

        params = {
            "nomerge": 1,
            "hide": "reminder_only",
            "after": after,
            "before": before,
            "locale": "en-GB",
            "include_message": "email",
            "_": str(int(time.time() * 1000)),
        }

        # print(params)

        # Send GET request
        response = httpx.get(URI, params=params)

        response = response.json()

        bin_collection = response["events"]

        # print(bin_collection)

        # Extract "end_day" and "name"
        events = [
            (event["end_day"], flag["name"])
            for event in bin_collection
            for flag in event.get("flags", [])
        ]

        # Print results
        for end_day, bin_type in events:

            date = datetime.strptime(end_day, "%Y-%m-%d")

            dict_data = {
                "type": bin_type,
                "collectionDate": date.strftime(date_format),
            }
            bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Redcar and Cleveland"
URL = "https://www.redcar-cleveland.gov.uk"
TEST_CASES = {}


class Source:
    def __init__(self, postcode: str | None = None, house_number: str | None = None):
        self.postcode = postcode
        self.house_number = house_number
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        kwargs = {}
        if self.postcode: kwargs['postcode'] = self.postcode
        if self.house_number: kwargs['paon'] = self.house_number

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
