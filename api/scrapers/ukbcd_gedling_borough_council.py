from datetime import datetime

import httpx
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.compat import httpx_helpers as _http


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page: str, **kwargs) -> dict:
        data = {"bins": []}

        user_paon = kwargs.get("paon")
        user_postcode = kwargs.get("postcode")

        address_query = ""
        if user_paon and user_postcode:
            address_query = f"{user_paon} {user_postcode}"
        elif user_postcode:
            address_query = user_postcode
        elif user_paon:
            address_query = user_paon

        if not address_query:
            raise ValueError(
                "Supply a postcode, or house number + postcode, to look up "
                "your Gedling bin collection schedule."
            )

        response = await _http.get(
            "https://api.gbcbincalendars.co.uk/get-bin-collection-calendar",
            params={"address": address_query},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/134.0.0.0 Safari/537.36",
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

        if not result.get("collections"):
            return data

        run_date = datetime.now().date()

        for month_block in result["collections"]:
            for entry in month_block.get("dates", []):
                bin_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
                if bin_date < run_date:
                    continue
                for service in entry.get("collections", []):
                    data["bins"].append(
                        {
                            "type": service,
                            "collectionDate": bin_date.strftime(date_format),
                        }
                    )

        data["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

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
        from datetime import datetime

        kwargs = {}
        if self.house_number: kwargs['paon'] = self.house_number

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
