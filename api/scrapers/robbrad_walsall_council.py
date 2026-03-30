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

        URI = f"https://cag.walsall.gov.uk/BinCollections/GetBins?uprn={user_uprn}"

        headers = {
            "user-agent": "Mozilla/5.0",
        }

        response = httpx.get(URI, headers=headers)

        soup = BeautifulSoup(response.text, "html.parser")
        # Extract links to collection schedule pages and iterate through the pages
        schedule_links = soup.findAll("td")

        for item in schedule_links:
            if "roundname" in item.contents[1]["href"]:
                # get bin colour
                bin_colour = (
                    item.contents[1]["href"].split("=")[-1].split("%")[0].upper()
                )
                bin_url = "https://cag.walsall.gov.uk" + item.contents[1]["href"]
                r = httpx.get(bin_url, headers=headers)
                if r.status_code != 200:
                    print(
                        f"Collection details for {bin_colour.lower()} bin could not be retrieved."
                    )
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                table = soup.findAll("tr")
                for tr in table:
                    td = tr.findAll("td")
                    if td:
                        dict_data = {
                            "type": bin_colour.capitalize() + " bin",
                            "collectionDate": datetime.strptime(
                                td[1].text.strip(), "%d/%m/%Y"
                            ).strftime("%d/%m/%Y"),
                        }
                        bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Walsall"
URL = "https://cag.walsall.gov.uk/"
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
