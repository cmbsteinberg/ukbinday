import httpx
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page: str, **kwargs) -> dict:
        user_postcode = kwargs.get("postcode")
        check_postcode(user_postcode)

        user_paon = kwargs.get("paon")

        bindata = {"bins": []}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }

        session = httpx.AsyncClient(follow_redirects=True)
        session.headers.update(headers)

        # Step 1: Search the Jadu directory with the postcode as keywords.
        # The directory at /directory/12 is "Rubbish Collection Calendar" with
        # one record per street/area. Each record lists which postcodes it covers.
        search_url = "https://www.shetland.gov.uk/directory/search"
        response = await session.get(
            search_url,
            params={"directoryID": "12", "keywords": user_postcode},
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        result_list = soup.find("ul", class_="list--record")

        if not result_list:
            raise ValueError(
                f"No collection records found for postcode {user_postcode}. "
                "Check the postcode is within the Shetland Islands."
            )

        # Collect all record links from the search results
        record_links = []
        for li in result_list.find_all("li"):
            a = li.find("a", href=True)
            if a:
                record_links.append(
                    (a["href"], a.get_text(strip=True))
                )

        if not record_links:
            raise ValueError(
                f"No collection records found for postcode {user_postcode}."
            )

        # If paon (house number/street name) is provided and there are
        # multiple results, try to match the street name
        selected_link = record_links[0]
        if user_paon and len(record_links) > 1:
            paon_lower = user_paon.lower().strip()
            for href, name in record_links:
                if paon_lower in name.lower():
                    selected_link = (href, name)
                    break

        record_path = selected_link[0]

        # Step 2: Fetch the individual record page
        record_url = f"https://www.shetland.gov.uk{record_path}"
        response = await session.get(record_url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Step 3: Parse the definition list for collection day fields.
        # Jadu renders directory record fields as <dl>/<dt>/<dd> pairs.
        dl = soup.find("dl")
        if not dl:
            raise ValueError(
                "Could not parse collection data from the record page."
            )

        dts = dl.find_all("dt")
        dds = dl.find_all("dd")

        for dt, dd in zip(dts, dds):
            label = dt.get_text(strip=True)
            # Match fields like "Recycling Collection Day" or
            # "Rubbish Collection Day"
            if "Collection Day" in label:
                day_name = dd.get_text(strip=True)
                if day_name in days_of_week:
                    # Strip " Day" suffix to get a cleaner bin type name
                    # e.g. "Recycling Collection Day" -> "Recycling Collection"
                    bin_type = label.replace(" Day", "").strip()

                    collection_date = get_next_day_of_week(day_name)

                    bindata["bins"].append(
                        {
                            "type": bin_type,
                            "collectionDate": collection_date,
                        }
                    )

        if not bindata["bins"]:
            raise ValueError(
                f"No collection days found for {selected_link[1]}."
            )

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(
                x.get("collectionDate"), date_format
            )
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Shetland Islands"
URL = "https://www.shetland.gov.uk"
TEST_CASES = {}


class Source:
    def __init__(self, postcode: str | None = None):
        self.postcode = postcode
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.postcode: kwargs['postcode'] = self.postcode

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
