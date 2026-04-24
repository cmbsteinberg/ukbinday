import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Wychavon District Council"
DESCRIPTION = "Source for wychavon.gov.uk waste collection."
URL = "https://www.wychavon.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "100120716273", "postcode": "WR3 7RU"},
}

BASE_URL = "https://selfservice.wychavon.gov.uk"
ADDRESS_URL = f"{BASE_URL}/sw2AddressLookupWS/jaxrs/PostCode"
SEARCH_URL = f"{BASE_URL}/wdcroundlookup/HandleSearchScreen"
JS_ENABLED_TOKEN = "TsOkrIPJrqo5nVGVChHj"

HEADERS = {"User-Agent": "Mozilla/5.0"}

ICON_MAP = {
    "Non-recyclable": "mdi:trash-can",
    "Recycling": "mdi:recycle",
    "Garden": "mdi:leaf",
    "Food": "mdi:food-apple",
}


class Source:
    def __init__(self, uprn: str | int, postcode: str | None = None):
        self._uprn = str(uprn)
        self._postcode = postcode or ""

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as s:
            # Step 1: address lookup by postcode
            r = await s.get(
                ADDRESS_URL,
                params={
                    "simple": "T",
                    "pcode": self._postcode,
                    "authority": "WDC",
                    "historical": "",
                },
                headers=HEADERS,
            )
            r.raise_for_status()
            addresses = r.json().get("jArray", [])

            address_text = ""
            for addr in addresses:
                if str(addr.get("UPRN")) == self._uprn:
                    address_text = addr.get("Address_Short", "")
                    break

            # Step 2: POST to get schedule
            r = await s.post(
                SEARCH_URL,
                headers=HEADERS,
                data={
                    "nmalAddrtxt": self._postcode,
                    "alAddrsel": self._uprn,
                    "txtPage": "std",
                    "txtSearchPerformedFlag": "false",
                    "futuredate": "",
                    "errstatus": "",
                    "address": address_text,
                    "jsenabled": JS_ENABLED_TOKEN,
                    "btnSubmit": "Next",
                },
            )
            r.raise_for_status()

        return _parse_schedule(r.text)


def _parse_schedule(html: str) -> list[Collection]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []


    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            bin_type_cell = cells[1].get_text(strip=True)
            date_cell = cells[2]

            bin_type_match = re.match(r"^([\w\s-]+collection)", bin_type_cell, re.I)
            if not bin_type_match:
                continue
            bin_type = bin_type_match.group(1).strip()

            # First bold date is next collection
            strong = date_cell.find("strong")
            if not strong:
                continue
            date_text = strong.get_text(strip=True)
            date_match = re.search(r"(\d{1,2}/\d{2}/\d{4})", date_text)
            if not date_match:
                continue

            try:
                dt = datetime.strptime(date_match.group(1), "%d/%m/%Y").date()
            except ValueError:
                continue

            icon = None
            for key, val in ICON_MAP.items():
                if key.lower() in bin_type.lower():
                    icon = val
                    break
            entries.append(Collection(date=dt, t=bin_type, icon=icon))

    return sorted(entries, key=lambda c: c.date)
