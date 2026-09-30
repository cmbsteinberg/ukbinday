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
        """
        Fetches bin collection dates for a given UPRN from the Armagh Banbridge Craigavon council website and returns them as structured bin data.

        Parameters:
            page (str): Ignored by this implementation.
            kwargs:
                uprn (str): Unique Property Reference Number used to look up the address schedule; required.

        Returns:
            dict: Dictionary with a "bins" key mapping to a list of collections.
        """
        user_uprn = kwargs.get("uprn")
        check_uprn(user_uprn)
        bindata = {"bins": []}

        # The council's WAF closes the connection on bare or minimal User-Agent
        # strings (manifests as requests.exceptions.ConnectionError with
        # RemoteDisconnected). A full modern browser UA passes cleanly.
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }

        def extract_bin_schedule(soup, heading_class):
            section_heading = soup.find("div", class_=heading_class)
            if not section_heading:
                return []
            content_col = section_heading.find_next("div", class_="col-sm-12 col-md-9")
            if not content_col:
                return []
            return [h4.get_text(strip=True) for h4 in content_col.find_all("h4")]

        url = f"https://www.armaghbanbridgecraigavon.gov.uk/resident/binday-result/?address={user_uprn}"

        session = httpx.AsyncClient(follow_redirects=True)
        session.headers.update(headers)
        response = await session.get(url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for collection in extract_bin_schedule(soup, "heading bg-black"):
            bindata["bins"].append({"collectionDate": collection, "type": "Domestic"})
        for collection in extract_bin_schedule(soup, "heading bg-green"):
            bindata["bins"].append({"collectionDate": collection, "type": "Recycling"})
        for collection in extract_bin_schedule(soup, "heading bg-brown"):
            bindata["bins"].append({"collectionDate": collection, "type": "Garden"})

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x["collectionDate"], "%d/%m/%Y")
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
