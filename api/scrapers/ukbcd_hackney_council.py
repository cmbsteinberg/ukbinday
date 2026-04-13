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

    async def parse_data(self, page: str, **kwargs) -> dict:

        user_paon = kwargs.get("paon")
        user_postcode = kwargs.get("postcode")
        check_postcode(user_postcode)
        check_paon(user_paon)
        bindata = {"bins": []}

        URI = "https://waste-api-hackney-live.ieg4.net/f806d91c-e133-43a6-ba9a-c0ae4f4cccf6/property/opensearch"

        data = {
            "Postcode": user_postcode,
        }
        headers = {"Content-Type": "application/json"}

        # Make the GET request
        response = await httpx.AsyncClient(follow_redirects=True).post(URI, json=data, headers=headers)

        addresses = response.json()

        for address in addresses["addressSummaries"]:
            summary = address["summary"]
            if user_paon in summary:
                systemId = address["systemId"]
        if systemId:
            URI = f"https://waste-api-hackney-live.ieg4.net/f806d91c-e133-43a6-ba9a-c0ae4f4cccf6/alloywastepages/getproperty/{systemId}"

            response = await httpx.AsyncClient(follow_redirects=True).get(URI)

            address = response.json()

            binIDs = address["providerSpecificFields"][
                "attributes_wasteContainersAssignableWasteContainers"
            ]
            for binID in binIDs.split(","):
                URI = f"https://waste-api-hackney-live.ieg4.net/f806d91c-e133-43a6-ba9a-c0ae4f4cccf6/alloywastepages/getbin/{binID}"
                response = await httpx.AsyncClient(follow_redirects=True).get(URI)
                getBin = response.json()

                bin_type = getBin["subTitle"]

                URI = f"https://waste-api-hackney-live.ieg4.net/f806d91c-e133-43a6-ba9a-c0ae4f4cccf6/alloywastepages/getcollection/{binID}"
                response = await httpx.AsyncClient(follow_redirects=True).get(URI)
                getcollection = response.json()

                collectionID = getcollection["scheduleCodeWorkflowIDs"][0]

                URI = f"https://waste-api-hackney-live.ieg4.net/f806d91c-e133-43a6-ba9a-c0ae4f4cccf6/alloywastepages/getworkflow/{collectionID}"
                response = await httpx.AsyncClient(follow_redirects=True).get(URI)
                collection_dates = response.json()

                dates = collection_dates["trigger"]["dates"]

                for date in dates:
                    parsed_datetime = datetime.strptime(
                        date, "%Y-%m-%dT%H:%M:%SZ"
                    ).strftime(date_format)

                    dict_data = {
                        "type": bin_type.strip(),
                        "collectionDate": parsed_datetime,
                    }
                    bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Hackney"
URL = "https://www.hackney.gov.uk"
TEST_CASES = {}


class Source:
    def __init__(self, postcode: str | None = None, house_number: str | None = None):
        self.postcode = postcode
        self.house_number = house_number
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.postcode: kwargs['postcode'] = self.postcode
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
