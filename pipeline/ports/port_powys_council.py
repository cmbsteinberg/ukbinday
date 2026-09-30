"""Powys County Council bin collections (GOSS Forms backend).

Flow (all plain HTTP, no browser needed):
  1. GET https://en.powys.gov.uk/binday — server-rendered GOSS form carrying
     pageSessionId/fsid/fsn tokens plus per-load NONCE in hidden inputs.
  2. POST the form to /apiserver/formsservice/http/processsubmission with the
     UPRN filled in and the NEXT button field set. The UPRN alone is enough —
     the postal-address lookup step can be skipped.
  3. The COLLECTIONDATES page renders one div.bdl-card per bin type, each with
     a bdl-card__header (bin type) and li dates ("Monday 7th September 2026").

Sibling template: port_hillingdon_council also talks to a GOSS apiserver, but
via the Alloy JSON-RPC method, not Forms — same platform family, different
flow. See pipeline/ports/README.md.

Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]

TITLE = "Powys County Council"
DESCRIPTION = "Source for powys.gov.uk bin collections."
URL = "https://en.powys.gov.uk/binday"
TEST_CASES = {
    "Test_001": {"uprn": "10011757177", "postcode": "HR3 5JS"},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
}

_LOGGER = logging.getLogger(__name__)

PAGE_URL = "https://en.powys.gov.uk/binday"


def _strip_ordinals(date_str: str) -> str:
    return re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = str(uprn).strip()

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True) as session:
            r1 = await session.get(PAGE_URL, headers=HEADERS, timeout=30)
            r1.raise_for_status()
            soup = BeautifulSoup(r1.text, "html.parser")

            form = soup.find("form", id="BINDAYLOOKUP_FORM")
            if not form or not form.get("action"):
                raise ValueError("Bin day lookup form not found on page")
            action = form["action"].replace("&amp;", "&")

            fields: dict[str, str] = {}
            for tag in soup.find_all("input", attrs={"name": True}):
                name = tag["name"]
                if name.startswith("BINDAYLOOKUP_"):
                    fields[name] = tag.get("value", "")

            fields["BINDAYLOOKUP_ADDRESSLOOKUP_UPRN"] = self._uprn
            fields["BINDAYLOOKUP_FORMACTION_NEXT"] = (
                "BINDAYLOOKUP_ADDRESSLOOKUP_ADDRESSLOOKUPBUTTONS"
            )

            r2 = await session.post(
                action,
                data=fields,
                headers={**HEADERS, "Referer": PAGE_URL},
                timeout=30,
            )
            r2.raise_for_status()

        return self._parse(r2.text)

    def _parse(self, html: str) -> list[Collection]:
        soup = BeautifulSoup(html, "html.parser")
        entries: list[Collection] = []

        for card in soup.find_all("div", class_="bdl-card"):
            header = card.find("div", class_="bdl-card__header")
            if header:
                for span in header.find_all("span", class_="bdl-card__icon"):
                    span.decompose()
            waste_type = header.get_text(strip=True) if header else "Unknown"
            icon = None
            lowered = waste_type.lower()
            if "garden" in lowered:
                icon = Icons.GARDEN
            elif "recycl" in lowered or "food" in lowered:
                icon = Icons.RECYCLING
            elif "rubbish" in lowered or "refuse" in lowered or "grey" in lowered:
                icon = Icons.GENERAL_WASTE

            for li in card.find_all("li"):
                date_str = _strip_ordinals(li.get_text(strip=True))
                try:
                    dt = datetime.strptime(date_str, "%A %d %B %Y").date()
                except ValueError:
                    _LOGGER.warning("Could not parse date: %r", date_str)
                    continue
                entries.append(Collection(date=dt, t=waste_type, icon=icon))

        return entries
