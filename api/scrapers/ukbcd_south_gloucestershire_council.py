from datetime import timedelta

import httpx

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


def format_bin_data(key: str, date: datetime):
    formatted_date = date.strftime(date_format)
    servicename = key.get("hso_servicename")
    print(servicename)
    if re.match(r"^Recycl", servicename) is not None:
        return [ ("Recycling", formatted_date) ]
    elif re.match(r"^Refuse", servicename) is not None:
        return [("General Waste (Black Bin)", formatted_date)]
    elif re.match(r"^Garden", servicename) is not None:
        return [("Garden Waste (Green Bin)", formatted_date)]
    elif re.match(r"^Food", servicename) is not None:
        return [("Food Waste", formatted_date)]
    else:
        return None


class CouncilClass(AbstractGetBinDataClass):
    def parse_data(self, page: str, **kwargs) -> dict:
        """
        Parse waste collection data for the given UPRN and return upcoming bin collections within the next eight weeks.
        
        Parameters:
            page (str): Raw page content (unused by this implementation; included for signature compatibility).
            uprn (str, keyword): Unique Property Reference Number used to query the South Gloucestershire collection API.
        
        Returns:
            dict: A mapping with a "bins" key containing a list of collection entries. Each entry is a dict with:
                - "type" (str): Human-friendly bin type (e.g., "Recycling", "General Waste (Black Bin)").
                - "collectionDate" (str): Formatted collection date string.
        
        Raises:
            ValueError: If the API returns no collection data for the provided UPRN.
        """
        uprn = kwargs.get("uprn")
        check_uprn(uprn)

        api_url = (
            f"https://api.southglos.gov.uk/wastecomp/GetCollectionDetails"
            f"?uprn={uprn}"
        )

        headers = {"content-type": "application/json"}

        response = httpx.get(api_url, headers=headers)

        json_response = response.json()
        if not json_response:
            raise ValueError("No collection data found for provided UPRN.")

        collection_data = json_response.get('value')

        today = datetime.today()
        eight_weeks = datetime.today() + timedelta(days=8 * 7)
        data = {"bins": []}
        collection_tuple = []
        for collection in collection_data:
            print(collection)
            item = collection.get('hso_nextcollection')

            if not item:
                continue

            collection_date = datetime.fromisoformat(item)
            if today.date() <= collection_date.date() <= eight_weeks.date():
                bin_data = format_bin_data(collection, collection_date)
                if bin_data is not None:
                    for bin_date in bin_data:
                        collection_tuple.append(bin_date)

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

TITLE = "South Gloucestershire"
URL = "https://api.southglos.gov.uk/wastecomp/GetCollectionDetails"
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
