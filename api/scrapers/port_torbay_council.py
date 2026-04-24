import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Torbay Council"
DESCRIPTION = "Source for torbay.gov.uk waste collection."
URL = "https://www.torbay.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "10000016984", "postcode": "TQ1 1AG"},
}

RENDER_URL = "https://selfservice-torbay.servicebuilder.co.uk/renderform"
FORM_URL = f"{RENDER_URL}/Form"
FORM_KEY = "09B72FF904A21A4B01A72AB6CCF28DC95105031C"
OBJECT_TEMPLATE_ID = "62"
HEADERS = {"User-Agent": "Mozilla/5.0"}

ICON_MAP = {
    "Recycling": "mdi:recycle",
    "Domestic": "mdi:trash-can",
    "Garden": "mdi:leaf",
    "Food": "mdi:food-apple",
}


class Source:
    def __init__(self, uprn: str | int, postcode: str | None = None):
        self._uprn = str(uprn)
        self._postcode = postcode or ""

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as s:
            # Step 1: load form to get verification token and form GUID
            r = await s.get(
                f"{RENDER_URL}?t={OBJECT_TEMPLATE_ID}&k={FORM_KEY}",
                headers=HEADERS,
            )
            r.raise_for_status()
            token = _extract_token(r.text)
            form_guid = _extract_field(r.text, "FormGuid")

            # Step 2: submit form with UPRN
            r = await s.post(
                FORM_URL,
                headers=HEADERS,
                data={
                    "__RequestVerificationToken": token,
                    "FormGuid": form_guid,
                    "ObjectTemplateID": OBJECT_TEMPLATE_ID,
                    "Trigger": "submit",
                    "CurrentSectionID": "0",
                    "TriggerCtl": "",
                    "FF1168": f"U{self._uprn}",
                    "FF1168lbltxt": "Please select your address",
                    "FF1168-text": "",
                },
            )
            r.raise_for_status()

        return _parse_schedule(r.text)


def _extract_token(html: str) -> str:
    match = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', html)
    return match.group(1) if match else ""


def _extract_field(html: str, name: str) -> str:
    match = re.search(rf'name="{name}".*?value="([^"]+)"', html)
    return match.group(1) if match else ""


def _parse_schedule(html: str) -> list[Collection]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    # Structure: pairs of date div + service div inside row divs
    date_pattern = re.compile(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
        r"(\d{1,2})\s+(\w+)\s+(\d{4})"
    )

    all_divs = soup.find_all("div", class_="col")
    i = 0
    while i < len(all_divs) - 1:
        date_text = all_divs[i].get_text(strip=True)
        service_text = all_divs[i + 1].get_text(strip=True)
        match = date_pattern.search(date_text)
        if match:
            day, month, year = match.groups()
            try:
                dt = datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()
            except ValueError:
                i += 1
                continue
            bin_type = service_text.replace(" Collection Service", "")
            icon = None
            for key, val in ICON_MAP.items():
                if key.lower() in bin_type.lower():
                    icon = val
                    break
            entries.append(Collection(date=dt, t=bin_type, icon=icon))
            i += 2
        else:
            i += 1

    return sorted(entries, key=lambda c: c.date)
