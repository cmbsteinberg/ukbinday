# Eastbourne uses the same script.

import re

from bs4 import BeautifulSoup

from api.compat.ukbcd.common import *
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.compat import httpx_helpers as _http


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    async def parse_data(self, page: str, **kwargs) -> dict:

        try:
            user_uprn = kwargs.get("uprn")
            check_uprn(user_uprn)
            url = f"https://environmentfirst.co.uk/house.php?uprn={user_uprn}"
            if not user_uprn:
                # Backwards compatibility for users who stored a URL.
                url = kwargs.get("url")
        except Exception as e:
            raise ValueError(f"Error getting identifier: {str(e)}")

        page = await _http.get(url)
        if "mysqli_sql_exception" in page.text or "Fatal error" in page.text:
            # The site occasionally returns HTTP 200 with a PHP fatal error
            # in the body instead of any markup, when EnvironmentFirst's own
            # database is unreachable - see #2127. That's an outage on their
            # end, not something a UPRN retry can fix, so raise a clear
            # message rather than silently returning no bins.
            raise ConnectionError(
                "EnvironmentFirst's bin lookup service is returning a server "
                "error (their database is unreachable) - this is an outage "
                "on their end, not this scraper. Try again later."
            )
        soup = BeautifulSoup(page.text, features="html.parser")
        soup.prettify()

        data = {"bins": []}
        collect_div = soup.find("div", {"class": "collect"})
        if collect_div is None:
            return data

        date_pattern = re.compile(r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})")

        for p in collect_div.find_all("p"):
            strong = p.find("strong")
            if not strong:
                continue
            label = p.get_text(" ", strip=True).lower()
            if "rubbish" in label:
                bin_type = "Rubbish"
            elif "recycling" in label:
                bin_type = "Recycling"
            elif "garden" in label:
                bin_type = "Garden"
            else:
                continue
            match = date_pattern.search(strong.get_text(" ", strip=True))
            if not match:
                continue
            cleaned = remove_ordinal_indicator_from_date_string(match.group(1))
            try:
                collection_date = datetime.strptime(cleaned, "%d %B %Y").strftime(
                    date_format
                )
            except ValueError:
                continue
            data["bins"].append(
                {
                    "type": bin_type,
                    "collectionDate": collection_date,
                }
            )

        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Lewes"
URL = "https://www.lewes-eastbourne.gov.uk/article/1158/When-is-my-bin-collection-day"
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
