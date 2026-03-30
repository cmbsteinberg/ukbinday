import ast

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

        pass  # urllib3 warnings disabled
        s = httpx.Client(follow_redirects=True)

        service_type_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
            "image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "Referer": "https://www.bristol.gov.uk/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
            "Sec-GPC": "1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, "
            "like Gecko) Chrome/134.0.0.0 Safari/537.36",
        }
        service_type_params = {
            "servicetypeid": "7dce896c-b3ba-ea11-a812-000d3a7f1cdc",
        }
        response = s.get(
            "https://bristolcouncil.powerappsportals.com/completedynamicformunauth/",
            params=service_type_params,
            headers=service_type_headers,
        )

        llpg_headers = {
            "Accept": "*/*",
            "Accept-Language": "en-GB,en;q=0.9",
            "Connection": "keep-alive",
            "Ocp-Apim-Subscription-Key": "47ffd667d69c4a858f92fc38dc24b150",
            "Ocp-Apim-Trace": "true",
            "Origin": "https://bristolcouncil.powerappsportals.com",
            "Referer": "https://bristolcouncil.powerappsportals.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
            "Sec-GPC": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, "
            "like Gecko) Chrome/134.0.0.0 Safari/537.36",
        }
        llpg_uprn = "UPRN" + user_uprn
        llpg_json_data = {
            "Uprn": llpg_uprn,
        }
        response = s.post(
            "https://bcprdapidyna002.azure-api.net/bcprdfundyna001-llpg/DetailedLLPG",
            headers=llpg_headers,
            json=llpg_json_data,
        )

        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-GB,en;q=0.9",
            "Connection": "keep-alive",
            # Already added when you pass json=
            # 'Content-Type': 'application/json',
            "Ocp-Apim-Subscription-Key": "47ffd667d69c4a858f92fc38dc24b150",
            "Ocp-Apim-Trace": "true",
            "Origin": "https://bristolcouncil.powerappsportals.com",
            "Referer": "https://bristolcouncil.powerappsportals.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
            "Sec-GPC": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        }
        json_data = {
            "uprn": user_uprn,
        }
        response = s.post(
            "https://bcprdapidyna002.azure-api.net/bcprdfundyna001-alloy/NextCollectionDates",
            headers=headers,
            json=json_data,
        )

        # Make a BS4 object
        soup = BeautifulSoup(response.text, features="html.parser")
        soup.prettify()

        # Soup returns API response rather than HTML, so parse those strings
        string_data = soup.text.split("data")[1]
        collection_data = string_data.split("]}")

        # Remove the spare ] and , characters at the of each list element
        fixed_data = [i[1:] for i in collection_data]

        # Remove the last list element since it's garbage (funny since this is a bin project)
        fixed_data.pop()
        collection_data.clear()

        # Make some more changes:
        idx = 0
        for i in fixed_data:
            if idx == 0:
                # Remove two extra characters if it's the first element
                i = i[2:]
            # Append some characters to the end of each line to make to dict
            i = i + "]}"
            idx += 1
            # Reuse the collection_data list to make a list of dictionaries - one for each bin
            collection_data.append(ast.literal_eval(i))

        collections = []
        for bin in collection_data:
            if not bin["collection"]:
                continue  # Skip if there are no collection dates

            bin_type = bin["containerName"]
            next_collection = datetime.strptime(
                bin["collection"][0]["nextCollectionDate"], "%Y-%m-%dT%H:%M:%S"
            ).strftime(date_format)

            collections.append((bin_type, next_collection))

        ordered_data = sorted(collections, key=lambda x: x[1])
        data = {"bins": []}
        for item in ordered_data:
            dict_data = {"type": item[0], "collectionDate": item[1]}
            data["bins"].append(dict_data)

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "City of Bristol"
URL = "https://bristolcouncil.powerappsportals.com/completedynamicformunauth/?servicetypeid=7dce896c-b3ba-ea11-a812-000d3a7f1cdc"
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
