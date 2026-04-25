import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup, Tag

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


# import the wonderful Beautiful Soup and the URL grabber
class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page: str, **kwargs) -> dict:

        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)
        bindata = {"bins": []}

        URI = "https://fylde.gov.uk/resident/bins-recycling-and-rubbish/bin-collection-day"

        # Make the GET request
        session = httpx.AsyncClient(follow_redirects=True)
        response = await session.get(URI)
        response.raise_for_status()

        soup: BeautifulSoup = BeautifulSoup(response.text, "html.parser")
        iframe = soup.find("iframe", id="bartec-iframe")
        if not iframe or not isinstance(iframe, Tag):
            raise Exception("Unexpected response from fylde.gov.uk")

        search_res = re.search(r"(?<=Token=)(.*?)(?=&|$)", str(iframe["src"]))
        if search_res is None:
            raise Exception("Token could not be extracted from fylde.gov.uk")
        token = search_res.group(1)

        if not token:
            raise Exception("Token could not be extracted from fylde.gov.uk")

        token = urllib.parse.unquote(token)

        parameters = {
            "Method": "calendareventsfromtoken",
            "Token": token,
            "UPRN": user_uprn,
        }

        API_URL = "https://collectiveview.bartec-systems.com/R152"
        API_METHOD = "GetData.ashx"

        response = await session.get(f"{API_URL}/{API_METHOD}", params=parameters)
        response.raise_for_status()

        # Parse the JSON response
        bin_collection = response.json()
        if not (len(bin_collection) > 0 and "title" in bin_collection[0]):
            raise Exception("Unexpected response from fylde.gov.uk API")

        today = datetime.now()

        REGEX_JOB_NAME = r"(?i)Empty Bin\s+(?P<bin_type>\S+(?:\s+\S+)?)"
        # Loop through each collection in bin_collection
        for collection in bin_collection:
            bin_type = (
                re.search(REGEX_JOB_NAME, collection["title"])
                .group("bin_type")
                .strip()
                .title()
            )
            collection_date = datetime.fromtimestamp(
                int(collection["start"][6:-2]) / 1000
            )

            if collection_date < today:
                continue

            dict_data = {
                "type": bin_type,
                "collectionDate": collection_date.strftime("%d/%m/%Y"),
            }
            bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Fylde"
URL = "https://www.fylde.gov.uk"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None):
        self.uprn = uprn
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn

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
