import re
import httpx
from bs4 import BeautifulSoup
from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.compat import httpx_helpers as _http


class CouncilClass(AbstractGetBinDataClass):
    async def parse_data(self, page: str, **kwargs) -> dict:
        uprn = kwargs.get("uprn")
        check_uprn(uprn)

        url = f"https://www.n-kesteven.org.uk/bins/display?uprn={uprn}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        }
        response = await _http.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, features="html.parser")

        data = {"bins": []}

        bin_dates_div = soup.find("div", {"class": "bin-dates"})
        if not bin_dates_div:
            return data

        for li in bin_dates_div.find_all("li", {"class": "text-large"}):
            bin_type_span = li.find("span", {"class": "font-weight-bold"})
            if not bin_type_span:
                continue

            bin_type = bin_type_span.get_text(strip=True)

            date_strong = li.find("strong")
            if not date_strong:
                continue

            date_text = date_strong.get_text(strip=True)

            try:
                collection_date = datetime.strptime(date_text, "%A, %d %B %Y")

                full_text = li.get_text(strip=True)
                match = re.search(rf"{re.escape(bin_type)}\s+(.*?)\s+bin on", full_text)
                if match:
                    bin_description = match.group(1).strip()
                    if bin_description:
                        bin_type = f"{bin_type} {bin_description}"

                data["bins"].append(
                    {
                        "type": bin_type,
                        "collectionDate": collection_date.strftime(date_format),
                    }
                )
            except ValueError:
                continue

        data["bins"].sort(
            key=lambda x: datetime.strptime(x.get("collectionDate"), date_format)
        )

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "North Kesteven"
URL = "https://www.n-kesteven.org.uk/bins/display"
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
