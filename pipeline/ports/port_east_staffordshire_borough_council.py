import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "East Staffordshire Borough Council"
DESCRIPTION = "Source for eaststaffsbc.gov.uk waste collection."
URL = "https://www.eaststaffsbc.gov.uk"
TEST_CASES = {
    "Test_001": {"postcode": "DE13 0BS", "house_number": "1 Fairham Road"},
}

BASE_URL = "https://www.eaststaffsbc.gov.uk/bins-rubbish-recycling/collection-dates"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

ICON_MAP = {
    "Blue Bag": "mdi:recycle",
    "Blue Bin": "mdi:recycle",
    "Brown Bin": "mdi:leaf",
    "Black Bin": "mdi:trash-can",
    "Weekly Food Waste": "mdi:food-apple",
}


class Source:
    def __init__(
        self,
        postcode: str,
        house_number: str = "",
        uprn: str | int | None = None,
    ):
        self._postcode = postcode
        self._house_number = house_number

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers=HEADERS) as client:
            property_id = await self._resolve_property_id(client)
            r = await client.get(f"{BASE_URL}/{property_id}")
            r.raise_for_status()

        return _parse_schedule(r.text)

    async def _resolve_property_id(self, client: httpx.AsyncClient) -> str:
        r = await client.get(BASE_URL, params={"postal_code": self._postcode})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        target = self._house_number.lower().strip()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/collection-dates/" not in href:
                continue
            text = a.get_text(strip=True).lower()
            if text == target or target.startswith(text) or text.startswith(target):
                return href.rstrip("/").rsplit("/", 1)[-1]

        raise ValueError(
            f"Address '{self._house_number}' not found for postcode {self._postcode}"
        )


def _parse_schedule(html: str) -> list[Collection]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[Collection] = []
    now = datetime.now()
    current_year = now.year
    next_year = current_year + 1

    day_pattern = re.compile(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
        r"(\d+)(?:st|nd|rd|th)?\s+(\w+)"
    )

    def _parse_date(text: str) -> datetime | None:
        m = day_pattern.search(text)
        if not m:
            return None
        day_num = int(m.group(2))
        try:
            dt = datetime.strptime(f"{day_num} {m.group(3)}", "%d %B")
        except ValueError:
            return None
        if now.month == 12 and dt.month == 1:
            return dt.replace(year=next_year)
        return dt.replace(year=current_year)

    next_section = soup.find("div", class_="collection-next")
    if next_section:
        h2 = next_section.find("h2")
        if h2:
            dt = _parse_date(h2.text)
            if dt:
                for item in next_section.find_all("div", class_="field__item"):
                    bin_type = item.get_text(strip=True)
                    icon = ICON_MAP.get(bin_type)
                    entries.append(Collection(date=dt.date(), t=bin_type, icon=icon))

    for li in soup.find_all("li"):
        text = li.contents[0].strip() if li.contents else ""
        dt = _parse_date(text)
        if not dt:
            continue
        for item in li.find_all("div", class_="field__item"):
            bin_type = item.get_text(strip=True)
            icon = ICON_MAP.get(bin_type)
            entries.append(Collection(date=dt.date(), t=bin_type, icon=icon))

    return sorted(entries, key=lambda c: c.date)
