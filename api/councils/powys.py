"""Powys: submit the GOSS bin-day form with the UPRN and parse its collection cards."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

PAGE_URL = "https://en.powys.gov.uk/binday"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
}


def _strip_ordinals(date_str: str) -> str:
    return re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)


def _parse(html: str) -> list[Collection]:
    page = soup(html)
    entries: list[Collection] = []

    for card in page.find_all("div", class_="bdl-card"):
        header = card.find("div", class_="bdl-card__header")
        if header:
            for span in header.find_all("span", class_="bdl-card__icon"):
                span.decompose()
        waste_type = header.get_text(strip=True) if header else "Unknown"

        for li in card.find_all("li"):
            date_str = _strip_ordinals(li.get_text(strip=True))
            try:
                day = datetime.strptime(date_str, "%A %d %B %Y").date()
            except ValueError:
                continue
            entries.append(Collection(day, waste_type))

    return entries


class Powys(Scraper):
    meta = Meta(
        title="Powys County Council",
        url=PAGE_URL,
        lads=("W06000023",),
        cases={"Test_001": {"uprn": "10011757177", "postcode": "HR3 5JS"}},
    )
    requires = frozenset({"uprn"})
    headers = HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r1 = await http.get(PAGE_URL, timeout=30)
        page = soup(r1.text)

        form = page.find("form", id="BINDAYLOOKUP_FORM")
        action = form.get("action") if form else None
        if not isinstance(action, str) or not action:
            raise UpstreamError("Bin day lookup form not found on page")
        action = action.replace("&amp;", "&")

        fields: dict[str, str] = {}
        for tag in page.find_all("input", attrs={"name": True}):
            name = tag.get("name")
            if isinstance(name, str) and name.startswith("BINDAYLOOKUP_"):
                value = tag.get("value", "")
                fields[name] = value if isinstance(value, str) else ""

        fields["BINDAYLOOKUP_ADDRESSLOOKUP_UPRN"] = address.need("uprn")
        fields["BINDAYLOOKUP_FORMACTION_NEXT"] = (
            "BINDAYLOOKUP_ADDRESSLOOKUP_ADDRESSLOOKUPBUTTONS"
        )

        r2 = await http.post(
            action,
            data=fields,
            headers={"Referer": PAGE_URL},
            timeout=30,
        )
        return _parse(r2.text)


SCRAPER = Powys()
