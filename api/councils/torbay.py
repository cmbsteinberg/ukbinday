"""Torbay: submits the UPRN to its self-service form and parses the returned collection schedule."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_TITLE = "Torbay Council"
_URL = "https://www.torbay.gov.uk"
_RENDER_URL = "https://selfservice-torbay.servicebuilder.co.uk/renderform"
_FORM_URL = f"{_RENDER_URL}/Form"
_FORM_KEY = "09B72FF904A21A4B01A72AB6CCF28DC95105031C"
_OBJECT_TEMPLATE_ID = "62"
_RENDER_PAGE_URL = f"{_RENDER_URL}?t={_OBJECT_TEMPLATE_ID}&k={_FORM_KEY}"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_DATE_PATTERN = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"(\d{1,2})\s+(\w+)\s+(\d{4})"
)


def _extract_token(html: str) -> str:
    match = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', html)
    return match.group(1) if match else ""


def _extract_field(html: str, name: str) -> str:
    match = re.search(rf'name="{name}".*?value="([^"]+)"', html)
    return match.group(1) if match else ""


def _parse_schedule(html: str) -> list[Collection]:
    page = soup(html)
    entries: list[Collection] = []
    all_divs = page.find_all("div", class_="col")
    i = 0
    while i < len(all_divs) - 1:
        date_text = all_divs[i].get_text(strip=True)
        service_text = all_divs[i + 1].get_text(strip=True)
        match = _DATE_PATTERN.search(date_text)
        if match:
            day, month, year = match.groups()
            try:
                collection_date = datetime.strptime(
                    f"{day} {month} {year}", "%d %B %Y"
                ).date()
            except ValueError:
                i += 1
                continue
            bin_type = service_text.replace(" Collection Service", "")
            entries.append(Collection(date=collection_date, type=bin_type))
            i += 2
        else:
            i += 1

    return entries


class Torbay(Scraper):
    meta = Meta(
        title=_TITLE,
        url=_URL,
        lads=("E06000027",),
        cases={"Test_001": {"uprn": "10000016984"}},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.get(_RENDER_PAGE_URL, timeout=30.0)
        token = _extract_token(r.text)
        form_guid = _extract_field(r.text, "FormGuid")

        r = await http.post(
            _FORM_URL,
            timeout=30.0,
            data={
                "__RequestVerificationToken": token,
                "FormGuid": form_guid,
                "ObjectTemplateID": _OBJECT_TEMPLATE_ID,
                "Trigger": "submit",
                "CurrentSectionID": "0",
                "TriggerCtl": "",
                "FF1168": f"U{address.need('uprn')}",
                "FF1168lbltxt": "Please select your address",
                "FF1168-text": "",
            },
        )
        return _parse_schedule(r.text)


SCRAPER = Torbay()
