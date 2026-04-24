import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Northumberland County Council"
DESCRIPTION = "Source for northumberland.gov.uk waste collection."
URL = "https://www.northumberland.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "010096302588", "postcode": "NE65 0ZP"},
}

BASE_URL = "https://bincollection.northumberland.gov.uk"
HEADERS = {"User-Agent": "Mozilla/5.0"}

ICON_MAP = {
    "Recycling": "mdi:recycle",
    "General waste": "mdi:trash-can",
    "Garden waste": "mdi:leaf",
}


class Source:
    def __init__(self, uprn: str | int, postcode: str | None = None):
        self._uprn = str(uprn)
        self._postcode = postcode or ""

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as s:
            # Step 1: GET postcode page to get CSRF token
            r = await s.get(f"{BASE_URL}/postcode", headers=HEADERS)
            r.raise_for_status()
            csrf = _extract_csrf(r.text)

            # Step 2: POST postcode
            r = await s.post(
                f"{BASE_URL}/postcode",
                headers=HEADERS,
                data={"_csrf": csrf, "postcode": self._postcode},
            )
            r.raise_for_status()
            csrf = _extract_csrf(r.text)

            # Step 3: POST address (UPRN) to get schedule
            r = await s.post(
                f"{BASE_URL}/address-select",
                headers=HEADERS,
                data={"_csrf": csrf, "address": self._uprn},
            )
            r.raise_for_status()

        return _parse_schedule(r.text)


def _extract_csrf(html: str) -> str:
    match = re.search(r'name=["\']_csrf["\'][^>]*value=["\']([^"\']+)', html)
    return match.group(1) if match else ""


def _parse_schedule(html: str) -> list[Collection]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    entries = []
    now = datetime.now()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        date_text = cells[0].get_text(strip=True)
        bin_type = cells[2].get_text(strip=True)
        try:
            dt = datetime.strptime(f"{date_text} {now.year}", "%d %B %Y").date()
            if dt < now.date():
                dt = datetime.strptime(f"{date_text} {now.year + 1}", "%d %B %Y").date()
        except ValueError:
            continue
        icon = ICON_MAP.get(bin_type)
        entries.append(Collection(date=dt, t=bin_type, icon=icon))

    return sorted(entries, key=lambda c: c.date)
