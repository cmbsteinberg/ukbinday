import httpx
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
        bindata = {"bins": []}

        URI = "https://selfserve.worcester.gov.uk/wccroundlookup/HandleSearchScreen"

        post_data = {
            "alAddrsel": user_uprn,
        }

        headers = {
            "referer": "https://selfserve.worcester.gov.uk/wccroundlookup/HandleSearchScreen",
            "content-type": "application/x-www-form-urlencoded",
        }

        response = httpx.post(URI, data=post_data, headers=headers)

        soup = BeautifulSoup(response.content, "html.parser")
        rows = soup.select("table.table tbody tr")

        for row in rows:
            bin_type = row.select_one("td:nth-of-type(2)").text.strip()
            collection_date = row.select_one("td:nth-of-type(3) strong").text.strip()

            # Skip if not applicable or if it's a sentence (not a date)
            if collection_date == "Not applicable":
                continue

            # Try to parse as date, skip if it fails (e.g., informational text)
            try:
                parsed_date = datetime.strptime(
                    collection_date,
                    "%A %d/%m/%Y",
                )
                dict_data = {
                    "type": bin_type,
                    "collectionDate": parsed_date.strftime("%d/%m/%Y"),
                }
                bindata["bins"].append(dict_data)
            except ValueError:
                # Skip entries that aren't valid dates (e.g., seasonal messages)
                continue

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Worcester"
URL = "https://www.Worcester.gov.uk"
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
