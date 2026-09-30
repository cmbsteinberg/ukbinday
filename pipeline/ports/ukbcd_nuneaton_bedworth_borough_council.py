import re
import urllib.parse
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from api.compat import httpx_helpers as _http
from api.compat.hacs import Collection  # type: ignore[attr-defined]
from api.compat.ukbcd.common import date_format
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass

# The council publishes one PDF calendar per collection day and week (A/B) for
# Oct 2026 - Sep 2027 (e.g. "bin-calendar-thursday-a"). Collections strictly
# alternate each week: in an A calendar black bins are on the weeks starting
# 2026-10-05, 2026-10-19, ... and brown/green bins on the weeks in between; a B
# calendar is the other way round. The PDFs (checked for all ten calendars)
# show exactly this, plus "no green bin collections from 17 January 2027,
# resuming 1 February" (brown only in that window).
CYCLE_FIRST_MONDAY = date(2026, 10, 5)
CYCLE_END = date(2027, 9, 30)
NO_GREEN_FROM = date(2027, 1, 17)
NO_GREEN_TO = date(2027, 1, 31)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]


class CouncilClass(AbstractGetBinDataClass):
    @staticmethod
    def _calendar_dates(filename: str) -> dict:
        m = re.fullmatch(r"bin-calendar-(\w+)-([ab])", filename)
        if not m or m.group(1) not in WEEKDAYS:
            raise ValueError(f"Unknown bin calendar: {filename}")
        weekday = WEEKDAYS.index(m.group(1))
        black_parity = 0 if m.group(2) == "a" else 1

        black: list[str] = []
        brown: list[str] = []
        green: list[str] = []
        day = CYCLE_FIRST_MONDAY - timedelta(days=7) + timedelta(days=weekday)
        while day <= CYCLE_END:
            if day >= date(2026, 10, 1):
                week = (day - CYCLE_FIRST_MONDAY).days // 7
                iso = day.isoformat()
                if week % 2 == black_parity:
                    black.append(iso)
                else:
                    brown.append(iso)
                    if not NO_GREEN_FROM <= day <= NO_GREEN_TO:
                        green.append(iso)
            day += timedelta(days=7)
        return {"Black Bin": black, "Brown Bin": brown, "Green Bin": green}

    async def parse_data(self, page: str, **kwargs) -> dict:

        data = {"bins": []}

        headers = {
            "Origin": "https://www.nuneatonandbedworth.gov.uk/",
            "Referer": "https://www.nuneatonandbedworth.gov.uk/",
            "User-Agent": "Mozilla/5.0",
        }

        street = urllib.parse.quote_plus(kwargs.get("paon"))
        base_url = "https://www.nuneatonandbedworth.gov.uk/"
        search_query = f"directory/search?directoryID=3&showInMap=&keywords={street}&search=Search+directory"

        search_response = await _http.get(base_url + search_query, headers=headers)

        if search_response.status_code == 200:
            soup = BeautifulSoup(search_response.content, "html.parser")
            street_link_tags = soup.find_all("a", class_="list__link")

            street_name = kwargs.get("paon").strip().lower()
            matches = [
                tag for tag in street_link_tags if street_name in tag.text.lower()
            ]

            if len(matches) > 1:
                exact = [t for t in matches if t.text.strip().lower() == street_name]
                if len(exact) == 1:
                    matches = exact

            if len(matches) == 1:
                street_url = matches[0]["href"]
                full_url = base_url.rstrip("/") + street_url
                bin_data = await self.get_bin_data(full_url)

                for k, v in bin_data.items():
                    for d in v:
                        dict_data = {
                            "type": k,
                            "collectionDate": datetime.strptime(
                                d, "%Y-%m-%d"
                            ).strftime(date_format),
                        }
                        data["bins"].append(dict_data)

                return data

            elif len(matches) > 1:
                raise ValueError("Multiple street URLs found. Please refine your search.")
            else:
                raise ValueError("Street URL not found.")
        else:
            raise ValueError("Failed to retrieve search results.")

        return data

    async def get_bin_data(self, url) -> dict:

        headers = {
            "Origin": "https://www.nuneatonandbedworth.gov.uk/",
            "Referer": "https://www.nuneatonandbedworth.gov.uk/",
            "User-Agent": "Mozilla/5.0",
        }

        bin_day_response = await _http.get(url, headers=headers)

        if bin_day_response.status_code == 200:
            soup = BeautifulSoup(bin_day_response.content, "html.parser")

            download_link = soup.find("a", {"href": re.compile(r"/downloads/file")})

            if download_link:
                file_url = download_link["href"]
                filename = file_url.split("/")[-1]
                output = self._calendar_dates(filename)
            else:
                raise ValueError("Bin data download link not found.")

        else:
            raise ValueError("Failed to retrieve bin data.")

        return output


# --- Adapter for Project API ---

TITLE = "Nuneaton and Bedworth"
URL = "https://www.nuneatonandbedworth.gov.uk"
TEST_CASES = {}


class Source:
    def __init__(
        self, house_number: str | None = None, street: str | None = None
    ):
        self.house_number = house_number
        self.street = street
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        # The council's directory is searched by street name; house_number is
        # only used for the legacy fixture that passes the street there.
        search = self.street or self.house_number
        if search:
            kwargs["paon"] = search

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
