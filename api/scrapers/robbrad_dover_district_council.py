import re
from datetime import datetime

from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *  # Consider specific imports
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass


class CouncilClass(AbstractGetBinDataClass):
    def parse_data(self, page: str, **kwargs) -> dict:

        try:
            user_uprn = kwargs.get("uprn")
            check_uprn(user_uprn)
            url = f"https://collections.dover.gov.uk/property/{user_uprn}"
            if not user_uprn:
                # This is a fallback for if the user stored a URL in old system. Ensures backwards compatibility.
                url = kwargs.get("url")
        except Exception as e:
            raise ValueError(f"Error getting identifier: {str(e)}")

        # Make a BS4 object
        page = httpx.get(url)
        soup = BeautifulSoup(page.text, "html.parser")

        bins_data = {"bins": []}
        bin_collections = []

        results_wrapper = soup.find("div", {"class": "results-table-wrapper"})
        if not results_wrapper:
            return bins_data  # Return empty if the results wrapper is not found

        bins = results_wrapper.find_all("div", {"class": "service-wrapper"})
        for bin_item in bins:
            service_name = bin_item.find("h3", {"class": "service-name"})
            next_service = bin_item.find("td", {"class": "next-service"})

            if service_name and next_service:
                bin_type = service_name.get_text().replace("Collection", "bin").strip()
                date_span = next_service.find("span", {"class": "table-label"})
                date_text = (
                    date_span.next_sibling.get_text().strip() if date_span else None
                )

                if date_text and re.match(r"\d{2}/\d{2}/\d{4}", date_text):
                    try:
                        bin_date = datetime.strptime(date_text, "%d/%m/%Y")
                        bin_collections.append((bin_type, bin_date))
                    except ValueError:
                        continue

        for bin_type, bin_date in sorted(bin_collections, key=lambda x: x[1]):
            bins_data["bins"].append(
                {
                    "type": bin_type.capitalize(),
                    "collectionDate": bin_date.strftime("%d/%m/%Y"),
                }
            )

        return bins_data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Dover"
URL = "https://collections.dover.gov.uk/property"
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
