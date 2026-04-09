from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
import httpx


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        api_url = "https://forms.n-somerset.gov.uk/Waste/CollectionSchedule"
        uprn = kwargs.get("uprn")
        postcode = kwargs.get("postcode")
        check_uprn(uprn)
        check_postcode(postcode)

        # Get schedule from API
        values = {
            "PreviousHouse": "",
            "PreviousPostcode": postcode,
            "Postcode": postcode,
            "SelectedUprn": uprn,
        }
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64)"}
        pass  # urllib3 warnings disabled
        response = httpx.request("POST", api_url, headers=headers, data=values)

        soup = BeautifulSoup(response.text, features="html.parser")

        rows = soup.find("table", {"class": re.compile("table")}).find_all("tr")

        # Form a JSON wrapper
        data = {"bins": []}

        # Loops the Rows
        for row in rows:
            cells = row.find_all("td")
            if cells:
                binType = cells[0].get_text(strip=True)
                collectionDate = (
                    cells[1].get_text(strip=True) + " " + datetime.now().strftime("%Y")
                )

                if len(cells) > 2:
                    nextCollectionDate = (
                        cells[2].get_text(strip=True) + " " + datetime.now().strftime("%Y")
                    )
                else:
                    nextCollectionDate = ""

                # Make each Bin element in the JSON
                dict_data = {
                    "type": binType,
                    "collectionDate": get_next_occurrence_from_day_month(
                        datetime.strptime(collectionDate, "%A %d %B %Y")
                    ).strftime(date_format),
                }

                # Add data to the main JSON Wrapper
                data["bins"].append(dict_data)

                # Make each next Bin element in the JSON
                if nextCollectionDate != "":
                    dict_data = {
                        "type": binType,
                        "collectionDate": get_next_occurrence_from_day_month(
                            datetime.strptime(nextCollectionDate, "%A %d %B %Y")
                        ).strftime(date_format),
                    }

                # Add data to the main JSON Wrapper
                data["bins"].append(dict_data)

        data["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "North Somerset"
URL = "https://forms.n-somerset.gov.uk/Waste/CollectionSchedule"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None, postcode: str | None = None):
        self.uprn = uprn
        self.postcode = postcode
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn
        if self.postcode: kwargs['postcode'] = self.postcode

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
