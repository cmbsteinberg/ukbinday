from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        data = {"bins": []}
        soup = BeautifulSoup(page.text, "html.parser")

        # Find all tables with the class "data-table confirmation"
        tables = soup.find_all("table", class_="data-table confirmation")
        for table in tables:
            rows = table.find_all("tr")
            bin_type = None
            bin_collection = None

            # Search for the bin color in the table headers
            th_element = table.find("th")
            if th_element:
                bin_type = th_element.text.strip()

            for row in rows:
                header = row.find("b")
                if header:
                    header_text = header.text.strip()
                    value_cell = row.find("td", class_="coltwo")
                    if value_cell:
                        value_text = value_cell.text.strip()

                        if header_text == "Collection Date":
                            bin_collection = value_text

            if bin_type and bin_collection:
                dict_data = {
                    "type": bin_type,
                    "collectionDate": datetime.strptime(
                        bin_collection, "%d/%m/%Y"
                    ).strftime(date_format),
                }

                data["bins"].append(dict_data)

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Oldham"
URL = "https://portal.oldham.gov.uk/bincollectiondates/details?uprn=422000033556"
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
