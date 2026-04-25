import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Swansea Council"
DESCRIPTION = "Source script for swansea.gov.uk"
URL = "https://swansea.gov.uk"
TEST_CASES = {
    "Cwmdonkin Drive": {"street": "cwmdonkin", "postcode": "SA20RA"},
    "Park Street": {"street": "Park Street", "postcode": "sa1 3dj"},
    "High Street": {"street": "High", "postcode": "SA1 1PE"},
    "St. Helen's": {"street": "St. Helen's", "postcode": "sa14nd"},
}

API_URL = "https://www1.swansea.gov.uk/recyclingsearch/"
ICON_MAP = {
    "PINK": "mdi:trash-can",
    "GREEN": "mdi:recycle",
}

COLOR_MAP = [  # HTML Colour, Bin Type, Icon Mapping
    ("MediumVioletRed", "Pink", "PINK"),
    ("ForestGreen", "Green", "GREEN"),
]

HEADERS = {
    "user-agent": "Mozilla/5.0",
}

_LOGGER = logging.getLogger(__name__)


class Source:
    def __init__(self, street=None, postcode=None):
        self._street = street
        self._postcode = postcode

    def get_asp_var(self, broth, id) -> str:
        asp_var = broth.find("input", {"id": id}).get("value")
        return asp_var

    async def fetch(self):
        # Initiate a session to generate required ASP variables
        session = httpx.AsyncClient(follow_redirects=True)
        session.headers.update(HEADERS)

        response0 = await session.get(API_URL)
        response0.raise_for_status()

        soup = BeautifulSoup(response0.text, "html.parser")

        data = {
            "__VIEWSTATE": self.get_asp_var(soup, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": self.get_asp_var(soup, "__VIEWSTATEGENERATOR"),
            "__VIEWSTATEENCRYPTED": "",
            "__EVENTVALIDATION": self.get_asp_var(soup, "__EVENTVALIDATION"),
            "txtRoadName": self._street,
            "txtPostCode": self._postcode,
            "btnSearch": "Search",
        }

        # Get the collection calendar
        response1 = await httpx.AsyncClient(follow_redirects=True).post(API_URL, data=data)
        response1.raise_for_status()

        soup = BeautifulSoup(response1.text, features="html.parser")

        tables = soup.find_all("table", {"title": "Calendar"})

        entries = []

        if not tables:  # no tables in HTML means the address lookup failed
            raise Exception("Address lookup failed")

        for table in tables:
            month_year_text = (
                table.find("td", width="70%").find("b").text.strip()
            )  # Extract month and year

            if not month_year_text:
                raise Exception("Cannot find month and year in Calendar")

            for color, bin_type, icon in COLOR_MAP:
                for td in table.find_all("td", bgcolor=color):
                    if not td:
                        raise Exception("Cannot find " + bin_type + " dates")

                    try:
                        date = datetime.strptime(
                            f"{td.text.strip()} {month_year_text}", "%d %B %Y"
                        ).date()
                    except ValueError:
                        _LOGGER.warning(
                            f"Skipped day='{td.text.strip()}', month_day='{month_year_text}'. Unexpected format."
                        )
                        continue

                    entries.append(
                        Collection(
                            date=date,
                            t=bin_type,
                            icon=ICON_MAP.get(icon),
                        )
                    )

        return entries
