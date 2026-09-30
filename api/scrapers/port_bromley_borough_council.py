import asyncio
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Bromley Borough Council"
DESCRIPTION = "Source for bromley.gov.uk waste collection."
URL = "https://recyclingservices.bromley.gov.uk"
TEST_CASES = {
    "Test_001": {"postcode": "BR1 3PU", "house_number": "17 College Road"},
}

BASE_URL = "https://recyclingservices.bromley.gov.uk/waste"
# The site's WAF answers 503 to the full Chrome-on-Linux UA string; a plain UA is served.
HEADERS = {"User-Agent": "Mozilla/5.0"}

ICON_MAP = {
    "Mixed Recycling": "mdi:recycle",
    "Non-Recyclable Refuse": "mdi:trash-can",
    "Paper & Cardboard": "mdi:newspaper-variant-outline",
    "Food Waste": "mdi:food-apple",
    "Garden Waste": "mdi:leaf",
}

MAX_POLLS = 10
POLL_INTERVAL_S = 2


class Source:
    def __init__(
        self,
        postcode: str,
        house_number: str = "",
        street: str = "",
        uprn: str | int | None = None,
    ):
        self._postcode = postcode
        self._house_number = house_number
        self._street = street

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=30.0, headers=HEADERS
        ) as client:
            property_id = await self._resolve_property_id(client)
            return await self._poll_schedule(client, property_id)

    async def _resolve_property_id(self, client: httpx.AsyncClient) -> str:
        r = await client.post(BASE_URL, data={"postcode": self._postcode})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        select = soup.find("select", attrs={"name": "address"})
        if not select:
            raise ValueError(f"No address selector found for postcode {self._postcode}")

        target = " ".join(f"{self._house_number} {self._street}".lower().split())
        for opt in select.find_all("option"):
            value = opt.get("value", "").strip()
            if not value:
                continue
            text = " ".join(opt.get_text(" ", strip=True).lower().replace(",", " ").split())
            if self._street:
                # "17 College Road, Bromley, BR1 3PU" or "6, Lynn Court, 36 Southend Road, ..."
                if text == target or text.startswith(f"{target} "):
                    return value
            elif target in text or text.startswith(target):
                return value

        raise ValueError(
            f"Address '{self._house_number}' not found for postcode {self._postcode}"
        )

    async def _poll_schedule(
        self, client: httpx.AsyncClient, property_id: str
    ) -> list[Collection]:
        # Initial request triggers server-side data processing
        await client.post(BASE_URL, data={"address": property_id, "go": "Go"})

        # WasteWorks processes data async; poll until schedule appears
        url = f"{BASE_URL}/{property_id}"
        for _ in range(MAX_POLLS):
            await asyncio.sleep(POLL_INTERVAL_S)
            r = await client.get(url)
            r.raise_for_status()
            entries = _parse_schedule(r.text)
            if entries:
                return entries

        raise TimeoutError(
            f"Schedule not ready after {MAX_POLLS * POLL_INTERVAL_S}s for property {property_id}"
        )


def _parse_schedule(html: str) -> list[Collection]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[Collection] = []
    current_year = datetime.now().year

    for service in soup.find_all("div", class_="waste-service-grid"):
        h3 = service.find("h3", class_="waste-service-name")
        if not h3:
            continue
        service_name = h3.get_text(strip=True)

        for row in service.find_all("div", class_="govuk-summary-list__row"):
            dt = row.find("dt", string="Next collection")
            if not dt:
                continue
            dd = dt.find_next_sibling()
            if not dd:
                continue
            text = dd.get_text(strip=True)
            date_part = text.split(",", 1)[-1].strip() if "," in text else text
            match = re.match(r"(\d+)\w*\s+(\w+)", date_part)
            if not match:
                continue
            day, month = match.groups()
            try:
                dt_obj = datetime.strptime(f"{day} {month} {current_year}", "%d %B %Y")
            except ValueError:
                continue
            if dt_obj < datetime.now():
                dt_obj = dt_obj.replace(year=current_year + 1)

            icon = None
            for key, val in ICON_MAP.items():
                if key.lower() in service_name.lower():
                    icon = val
                    break
            entries.append(Collection(date=dt_obj.date(), t=service_name, icon=icon))

    return sorted(entries, key=lambda c: c.date)
