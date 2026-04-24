import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Argyll and Bute Council"
DESCRIPTION = "Source for argyll-bute.gov.uk waste collection."
URL = "https://www.argyll-bute.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "000125011723", "postcode": "PA286LJ"},
}

BIN_URL = "https://www.argyll-bute.gov.uk/rubbish-and-recycling/household-waste/bin-collection"
HEADERS = {"User-Agent": "Mozilla/5.0"}

ICON_MAP = {
    "Recycling": "mdi:recycle",
    "General": "mdi:trash-can",
    "Garden": "mdi:leaf",
    "Food": "mdi:food-apple",
    "Glass": "mdi:glass-fragile",
}


class Source:
    def __init__(self, uprn: str | int, postcode: str | None = None):
        self._uprn = str(uprn)
        self._postcode = (postcode or "").replace(" ", "")

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as s:
            # Step 1: GET the page to get form_build_id
            r = await s.get(BIN_URL, headers=HEADERS)
            r.raise_for_status()
            form_build_id = _extract_form_build_id(r.text)

            # Step 2: POST postcode to get address list + new form_build_id
            r = await s.post(
                BIN_URL,
                headers=HEADERS,
                data={
                    "postcode": self._postcode,
                    "form_build_id": form_build_id,
                    "form_id": "abc_bins_dates_lookup_form",
                    "op": "Search for my bin collection details",
                },
            )
            r.raise_for_status()
            form_build_id = _extract_form_build_id(r.text)

            # Step 3: POST with UPRN to get schedule
            r = await s.post(
                BIN_URL,
                headers=HEADERS,
                data={
                    "postcode": self._postcode,
                    "address": self._uprn,
                    "form_build_id": form_build_id,
                    "form_id": "abc_bins_dates_lookup_form",
                    "op": "Search for my bin collection details",
                },
            )
            r.raise_for_status()

        return _parse_schedule(r.text)


def _extract_form_build_id(html: str) -> str:
    match = re.search(r'name="form_build_id"\s+value="([^"]+)"', html)
    return match.group(1) if match else ""


def _parse_schedule(html: str) -> list[Collection]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="table")
    if not table:
        return []

    entries = []
    now = datetime.now()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        bin_type = cells[0].get_text(strip=True)
        date_text = cells[1].get_text(strip=True)
        try:
            dt = datetime.strptime(f"{date_text} {now.year}", "%A %d %B %Y").date()
            if dt < now.date():
                dt = datetime.strptime(f"{date_text} {now.year + 1}", "%A %d %B %Y").date()
        except ValueError:
            continue
        icon = ICON_MAP.get(bin_type)
        entries.append(Collection(date=dt, t=bin_type, icon=icon))

    return sorted(entries, key=lambda c: c.date)
