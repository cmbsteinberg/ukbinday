from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class CouncilClass(AbstractGetBinDataClass):
    def parse_data(self, page: str, **kwargs) -> dict:

        try:
            user_uprn = kwargs.get("uprn")
            check_uprn(user_uprn)
            url = f"https://bincollection.newham.gov.uk/Details/Index/{user_uprn}"
            if not user_uprn:
                # This is a fallback for if the user stored a URL in old system. Ensures backwards compatibility.
                url = kwargs.get("url")
        except Exception as e:
            raise ValueError(f"Error getting identifier: {str(e)}")

        # Make a BS4 object
        page = httpx.get(url, verify=False)
        soup = BeautifulSoup(page.text, "html.parser")
        soup.prettify

        # Form a JSON wrapper
        data = {"bins": []}

        # Find section with bins in
        sections = soup.find_all("div", {"class": "card h-100"})

        # there may also be a recycling one too
        sections_recycling = soup.find_all(
            "div", {"class": "card h-100 card-recycling"}
        )
        if len(sections_recycling) > 0:
            sections.append(sections_recycling[0])

        # as well as one for food waste
        sections_food_waste = soup.find_all(
            "div", {"class": "card h-100 card-food"}
        )
        if len(sections_food_waste) > 0:
            sections.append(sections_food_waste[0])

        # For each bin section, get the text and the list elements
        for item in sections:
            header = item.find("div", {"class": "card-header"})
            bin_type_element = header.find_next("b")
            if bin_type_element is not None:
                bin_type = bin_type_element.text
                array_expected_types = ["Domestic", "Recycling", "Food Waste"]
                if bin_type in array_expected_types:
                    date = (
                        item.find_next("p", {"class": "card-text"})
                        .find_next("mark")
                        .next_sibling.strip()
                    )
                    next_collection = datetime.strptime(date, "%m/%d/%Y")

                    dict_data = {
                        "type": bin_type,
                        "collectionDate": next_collection.strftime(date_format),
                    }
                    data["bins"].append(dict_data)

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Newham"
URL = "https://bincollection.newham.gov.uk/"
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
