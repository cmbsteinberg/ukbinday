from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page: str, **kwargs) -> dict:
        # Get and check UPRN
        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)
        bindata = {"bins": []}

        uri = "https://waste.southhams.gov.uk/mycollections"

        s = httpx.AsyncClient(follow_redirects=True)
        r = await s.get(uri)
        for cookie in r.cookies.jar:
            if cookie.name == "fcc_session_cookie":
                fcc_session_token = cookie.value

        uri = "https://waste.southhams.gov.uk/mycollections/getcollectiondetails"

        params = {
            "fcc_session_token": fcc_session_token,
            "uprn": user_uprn,
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            "Referer": "https://waste.southhams.gov.uk/mycollections",
            "X-Requested-With": "XMLHttpRequest",
        }

        # Send a POST request with form data and headers
        r = await s.post(uri, data=params, headers=headers)

        result = r.json()

        for collection in result["binCollections"]["tile"]:

            # Parse the HTML with BeautifulSoup
            soup = BeautifulSoup(collection[0], "html.parser")
            soup.prettify()

            # Find all collectionDiv elements
            collections = soup.find_all("div", class_="collectionDiv")

            # Process each collectionDiv
            for collection in collections:
                # Extract the service name
                service_name = collection.find("h3").text.strip()

                # Extract collection frequency and day
                details = collection.find("div", class_="detWrap").text.strip()

                # Extract the next collection date
                next_collection = details.split("Your next scheduled collection is ")[
                    1
                ].split(".")[0]

                if next_collection.startswith("today"):
                    next_collection = next_collection.split("today, ")[1]
                elif next_collection.startswith("tomorrow"):
                    next_collection = next_collection.split("tomorrow, ")[1]

                dict_data = {
                    "type": service_name,
                    "collectionDate": datetime.strptime(
                        next_collection, "%A, %d %B %Y"
                    ).strftime(date_format),
                }
                bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "South Hams"
URL = "https://www.southhams.gov.uk"
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
