import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import check_uprn
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs: Any) -> Dict[str, List[Dict[str, str]]]:
        data: Dict[str, List[Dict[str, str]]] = {"bins": []}

        uprn: Optional[str] = kwargs.get("uprn")

        if uprn is None:
            raise ValueError("UPRN is required and must be a non-empty string.")

        check_uprn(uprn)  # Assuming check_uprn() raises an exception if UPRN is invalid

        try:
            response = httpx.post(
                f"https://wastecollections.haringey.gov.uk/property/{uprn}",
                timeout=10,  # Set a timeout for the request
            )
            response.raise_for_status()  # This will raise an exception for HTTP errors
        except httpx.HTTPError as e:
            logging.error(f"Network or HTTP error occurred: {e}")
            raise ConnectionError("Failed to retrieve data.") from e

        try:
            soup = BeautifulSoup(response.text, features="html.parser")
            soup.prettify()

            sections = soup.find_all("div", {"class": "property-service-wrapper"})

            date_regex = re.compile(r"\d{2}/\d{2}/\d{4}")
            for section in sections:
                service_name_element = section.find("h3", {"class": "service-name"})
                next_service_element = section.find("tbody").find(
                    "td", {"class": "next-service"}
                )

                if service_name_element and next_service_element:
                    service = service_name_element.text
                    next_collection = next_service_element.find(string=date_regex)

                    if next_collection:
                        dict_data = {
                            "type": service.replace("Collect ", "")
                            .replace("Paid ", "")
                            .strip(),
                            "collectionDate": next_collection.strip(),
                        }
                        data["bins"].append(dict_data)
        except Exception as e:
            logging.error(f"Error parsing data: {e}")
            raise ValueError("Error processing the HTML data.") from e

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Haringey"
URL = "https://wastecollections.haringey.gov.uk/property"
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
