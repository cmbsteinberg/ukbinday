import httpx
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.compat import httpx_helpers as _http


# import the wonderful Beautiful Soup and the URL grabber
class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page: str, **kwargs) -> dict:

        """
        Fetches bin collection dates for a given UPRN from the Armagh Banbridge Craigavon council website and returns them as structured bin data.
        
        Parameters:
            page (str): Ignored by this implementation.
            kwargs:
                uprn (str): Unique Property Reference Number used to look up the address schedule; required.
        
        Returns:
            dict: Dictionary with a "bins" key mapping to a list of collections. Each collection is a dict with:
                - "collectionDate" (str): Date in "DD/MM/YYYY" format.
                - "type" (str): One of "Domestic", "Recycling", or "Garden".
            The list is sorted in ascending order by the parsed collection date (format "%d/%m/%Y").
        """
        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)
        bindata = {"bins": []}

        headers = {
            "user-agent": "Mozilla/5.0",
        }

        # Function to extract bin collection information
        def extract_bin_schedule(soup, heading_class):
            """
            Extracts bin collection date strings from the HTML section identified by the given heading class.
            
            Searches the parsed HTML for a div with the provided heading_class and returns the text content of all `h4` elements found in the associated content column.
            
            Parameters:
                soup (bs4.BeautifulSoup): Parsed HTML document to search.
                heading_class (str): CSS class of the section heading that identifies the bin schedule block.
            
            Returns:
                list[str]: A list of collection date strings found in the section; empty if none are present.
            """
            collections = []

            # Find the relevant section based on the heading class
            section_heading = soup.find("div", class_=heading_class)
            if section_heading:
                # Find all the bin collection dates in that section
                collection_dates = section_heading.find_next(
                    "div", class_="col-sm-12 col-md-9"
                ).find_all("h4")
                for date in collection_dates:
                    # Clean and add the date to the list
                    collections.append(date.get_text(strip=True))

            return collections

        # URL for bin collection schedule
        url = f"https://www.armaghbanbridgecraigavon.gov.uk/resident/binday-result/?address={user_uprn}"

        # Send a GET request to fetch the page content
        response = await _http.get(url, headers=headers)

        # Check if the request was successful
        if response.status_code == 200:
            # Parse the page content using BeautifulSoup
            soup = BeautifulSoup(response.text, "html.parser")

            # Extract bin collection schedules by their sections
            domestic_collections = extract_bin_schedule(soup, "heading bg-black")
            for collection in domestic_collections:
                bindata["bins"].append(
                    {"collectionDate": collection, "type": "Domestic"}
                )
            recycling_collections = extract_bin_schedule(soup, "heading bg-green")
            for collection in recycling_collections:
                bindata["bins"].append(
                    {"collectionDate": collection, "type": "Recycling"}
                )
            garden_collections = extract_bin_schedule(soup, "heading bg-brown")
            for collection in garden_collections:
                bindata["bins"].append({"collectionDate": collection, "type": "Garden"})

        else:
            print(f"Failed to retrieve data. Status code: {response.status_code}")

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Armagh City, Banbridge and Craigavon"
URL = "https://www.armaghbanbridgecraigavon.gov.uk/"
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
