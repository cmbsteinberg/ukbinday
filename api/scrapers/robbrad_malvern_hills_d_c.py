from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
import httpx


# import the wonderful Beautiful Soup and the URL grabber
class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        api_url = "https://swict.malvernhills.gov.uk/mhdcroundlookup/HandleSearchScreen"

        user_uprn = kwargs.get("uprn")
        # Check the UPRN is valid
        check_uprn(user_uprn)

        # Create the form data
        form_data = {"nmalAddrtxt": "", "alAddrsel": user_uprn}
        # expects postcode to be looked up and then uprn used.
        # we can just provide uprn

        # Make a request to the API
        pass  # urllib3 warnings disabled
        response = httpx.post(api_url, data=form_data)

        # Make a BS4 object
        soup = BeautifulSoup(response.text, features="html.parser")
        soup.prettify()

        # Find results table
        table_element = soup.find("table")
        table_body = table_element.find("tbody")
        rows = table_body.find_all("tr")

        data = {"bins": []}

        for row in rows:
            columns = row.find_all("td")
            columns = [ele.text.strip() for ele in columns]

            thisCollection = [ele for ele in columns if ele]  # Get rid of empty values

            # if not signed up for garden waste, this appears as Not applicable
            if "Not applicable" not in thisCollection[1]:
                bin_type = thisCollection[0].replace("collection", "").strip()
                date = datetime.strptime(thisCollection[1], "%A %d/%m/%Y")
                dict_data = {
                    "type": bin_type,
                    "collectionDate": date.strftime(date_format),
                }
                data["bins"].append(dict_data)

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Malvern Hills"
URL = "https://swict.malvernhills.gov.uk/mhdcroundlookup/HandleSearchScreen"
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
