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
        bindata = {"bins": []}

        URI = (
            f"https://maps.monmouthshire.gov.uk/?action=SetAddress&UniqueId={user_uprn}"
        )

        # Make the GET request
        response = httpx.get(URI)

        # Parse the HTML
        soup = BeautifulSoup(response.content, "html.parser")

        waste_collections_div = soup.find("div", {"aria-label": "Waste Collections"})

        # Find all bin collection panels
        bin_panels = waste_collections_div.find_all("div", class_="atPanelContent")

        current_year = datetime.now().year
        current_month = datetime.now().month

        for panel in bin_panels:
            # Extract bin name (e.g., "Household rubbish bag")
            bin_name = panel.find("h4").text.strip().replace("\r", "").replace("\n", "")

            # Extract collection date (e.g., "Monday 9th December")
            date_tag = panel.find("p")
            if (
                date_tag
                and "Your next collection date is"
                in date_tag.text.strip().replace("\r", "").replace("\n", "")
            ):
                collection_date = date_tag.find("strong").text.strip()
            else:
                continue

            collection_date = datetime.strptime(
                remove_ordinal_indicator_from_date_string(collection_date), "%A %d %B"
            )

            if (current_month > 9) and (collection_date.month < 4):
                collection_date = collection_date.replace(year=(current_year + 1))
            else:
                collection_date = collection_date.replace(year=current_year)

            dict_data = {
                "type": bin_name,
                "collectionDate": collection_date.strftime("%d/%m/%Y"),
            }
            bindata["bins"].append(dict_data)

        bindata["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), "%d/%m/%Y")
        )

        return bindata


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Monmouthshire"
URL = "https://maps.monmouthshire.gov.uk"
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
