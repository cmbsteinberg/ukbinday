
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
        collections = []
        selected_collections = kwargs.get("paon").split(",")
        calendar_urls = []
        run_date = datetime.now().date()

        # For each collection, check if there's a number. Garden bins have no numbers, so we can generate the needed
        # URLs this way
        for item in selected_collections:
            item = item.strip().lower().replace(" ", "_")
            if has_numbers(item):
                calendar_urls.append(
                    f"https://www.gbcbincalendars.co.uk/json/gedling_borough_council_{item}_bin_schedule.json"
                )
            else:
                calendar_urls.append(
                    f"https://www.gbcbincalendars.co.uk/json/gedling_borough_council_{item}_garden_bin_schedule.json"
                )

        # Parse each URL and load future data
        for url in calendar_urls:
            response = httpx.get(url)
            if response.status_code != 200:
                raise ConnectionError(f"Could not get response from: {url}")
            json_data = response.json()["collectionDates"]
            for col in json_data:
                bin_date = datetime.strptime(
                    col.get("collectionDate"), "%Y-%m-%d"
                ).date()
                if bin_date >= run_date:
                    collections.append((col.get("alternativeName"), bin_date))

        # Sort the data
        ordered_data = sorted(collections, key=lambda x: x[1])
        data = {"bins": []}
        for bin in ordered_data:
            dict_data = {
                "type": bin[0],
                "collectionDate": bin[1].strftime(date_format),
            }
            data["bins"].append(dict_data)
        print()

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Gedling"
URL = "https://www.gedling.gov.uk/"
TEST_CASES = {}


class Source:
    def __init__(self, house_number: str | None = None):
        self.house_number = house_number
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        kwargs = {}
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
