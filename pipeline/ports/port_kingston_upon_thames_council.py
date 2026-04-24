import re
from datetime import datetime

from bs4 import BeautifulSoup

from api.compat.curl_cffi_fallback import AsyncClient
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Kingston upon Thames Council"
DESCRIPTION = "Source for waste-services.kingston.gov.uk waste collection."
URL = "https://www.kingston.gov.uk"
TEST_CASES = {
    "Test_001": {"postcode": "KT3 3EG", "house_number": "25 Beechcroft Avenue"},
}

WASTE_URL = "https://waste-services.kingston.gov.uk/waste"

ICON_MAP = {
    "Non-recyclable Refuse": "mdi:trash-can",
    "Mixed recycling": "mdi:recycle",
    "Paper and card": "mdi:newspaper-variant-outline",
    "Food waste": "mdi:food-apple",
    "Garden Waste": "mdi:leaf",
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
        async with AsyncClient(impersonate="safari") as client:
            property_id = await self._resolve_property_id(client)
            r = await client.get(f"{WASTE_URL}/{property_id}?page_loading=1")
            r.raise_for_status()

        return _parse_schedule(r.text)

    async def _resolve_property_id(self, client: AsyncClient) -> str:
        await client.get(WASTE_URL)
        r = await client.post(WASTE_URL, data={"postcode": self._postcode})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        target = self._house_number.lower().strip()
        select = soup.find("select", attrs={"name": "address"})
        if not select:
            raise ValueError(f"No address dropdown for postcode {self._postcode}")

        for opt in select.find_all("option"):
            val = opt.get("value", "")
            if not val:
                continue
            text = opt.get_text(strip=True).lower()
            if target in text or text.startswith(target):
                return val

        raise ValueError(
            f"Address '{self._house_number}' not found for postcode {self._postcode}"
        )


def _parse_schedule(html: str) -> list[Collection]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[Collection] = []
    now = datetime.now()

    date_pattern = re.compile(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
        r"(\d+)(?:st|nd|rd|th)?\s+(\w+)"
    )

    for grid in soup.find_all("div", class_="waste-service-grid"):
        h3 = grid.find("h3", class_="waste-service-name")
        if not h3:
            continue
        service_name = h3.get_text(strip=True)

        dl = grid.find("dl", class_="govuk-summary-list")
        if not dl:
            continue

        for row in dl.find_all("div", class_="govuk-summary-list__row"):
            dt = row.find("dt")
            if not dt or "next collection" not in dt.get_text(strip=True).lower():
                continue
            dd = row.find("dd")
            if not dd:
                continue

            date_text = dd.get_text(strip=True)
            date_text = re.sub(r"\(.*?\)", "", date_text).strip()

            m = date_pattern.search(date_text)
            if not m:
                continue

            day_num = int(m.group(2))
            try:
                dt_parsed = datetime.strptime(
                    f"{m.group(1)} {day_num} {m.group(3)} {now.year}",
                    "%A %d %B %Y",
                )
            except ValueError:
                continue

            if dt_parsed.date() < now.date():
                try:
                    dt_parsed = dt_parsed.replace(year=now.year + 1)
                except ValueError:
                    continue

            icon = ICON_MAP.get(service_name)
            entries.append(
                Collection(date=dt_parsed.date(), t=service_name, icon=icon)
            )

    return sorted(entries, key=lambda c: c.date)
