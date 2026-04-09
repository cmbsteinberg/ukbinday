import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass

HEADERS = {
    "user-agent": "Mozilla/5.0",
}


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete class implementing all abstract operations of the base class.
    """

    def get_session_variable(self, soup, id) -> str:
        """Extract ASP.NET variable from the HTML."""
        element = soup.find("input", {"id": id})
        if element:
            return element.get("value")
        else:
            raise ValueError(f"Unable to find element with id: {id}")

    def parse_data(self, page: str, **kwargs) -> dict:
        # Create a session to handle cookies and headers
        session = httpx.Client(follow_redirects=True)
        session.headers.update(HEADERS)
        user_uprn = kwargs.get("uprn")
        user_postcode = kwargs.get("postcode")
        URL = "https://www1.swansea.gov.uk/recyclingsearch/"

        # Get initial ASP.NET variables
        response = session.get(URL)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        data = {
            "__VIEWSTATE": self.get_session_variable(soup, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": self.get_session_variable(
                soup, "__VIEWSTATEGENERATOR"
            ),
            "__VIEWSTATEENCRYPTED": "",
            "__EVENTVALIDATION": self.get_session_variable(soup, "__EVENTVALIDATION"),
            "txtRoadName": user_uprn,
            "txtPostCode": user_postcode,
            "btnSearch": "Search",
        }

        # Get the collection calendar
        response = session.post(URL, data=data)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        next_refuse_date = soup.find("span", {"id": "lblNextRefuse"}).text.strip()
        next_recycling_date = soup.find("span", {"id": "lblNextRecycling"}).text.strip()

        bin_data = {
            "bins": [
                {"type": "Pink Week", "collectionDate": next_refuse_date},
                {"type": "Green Week", "collectionDate": next_recycling_date},
            ]
        }

        return bin_data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Swansea"
URL = "https://www1.swansea.gov.uk/recyclingsearch/"
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
