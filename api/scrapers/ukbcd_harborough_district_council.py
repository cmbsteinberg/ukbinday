import httpx
import urllib3
from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass

# Suppress SSL warnings when using verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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

        URI1 = "https://harborough.fccenvironment.co.uk/"
        URI2 = "https://harborough.fccenvironment.co.uk/detail-address"

        # Make the GET request
        session = httpx.AsyncClient(verify=False, follow_redirects=True)
        response = await session.get(
            URI1
        )  # Initialize session state (cookies) required by URI2
        response.raise_for_status()  # Validate session initialization

        params = {"Uprn": user_uprn}
        response = await session.post(URI2, data=params)

        # Check for service errors
        if response.status_code == 502:
            raise ValueError(
                f"The FCC Environment service is currently unavailable (502 Bad Gateway). "
                f"This is a temporary issue with the council's waste collection system. "
                f"Please try again later."
            )

        response.raise_for_status()

        soup = BeautifulSoup(response.content, features="html.parser")
        bin_collection = soup.find(
            "div", {"class": "blocks block-your-next-scheduled-bin-collection-days"}
        )

        if bin_collection is None:
            raise ValueError(
                f"Could not find bin collection data for UPRN {user_uprn}. "
                "The council website may have changed or the UPRN may be invalid."
            )

        lis = bin_collection.find_all("li")
        for li in lis:
            try:
                # Try the new format first (with span.pull-right)
                date_span = li.find("span", {"class": "pull-right"})
                if date_span:
                    date_text = date_span.text.strip()
                    date = datetime.strptime(date_text, "%d %B %Y").strftime("%d/%m/%Y")
                    # Extract bin type from the text before the span
                    bin_type = li.text.replace(date_text, "").strip()
                else:
                    # Fall back to old format (regex match)
                    split = re.match(r"(.+)\s(\d{1,2} \w+ \d{4})$", li.text)
                    if not split:
                        continue
                    bin_type = split.group(1).strip()
                    date = datetime.strptime(
                        split.group(2),
                        "%d %B %Y",
                    ).strftime("%d/%m/%Y")

                dict_data = {
                    "type": bin_type,
                    "collectionDate": date,
                }
                bindata["bins"].append(dict_data)
            except Exception:
                continue

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Harborough"
URL = "https://www.harborough.gov.uk"
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
