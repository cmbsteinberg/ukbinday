"""West Devon Borough Council bin collections (FCC Environment JSON backend).

Flow (plain HTTP, no browser needed):
  1. GET https://westdevon.fccenvironment.co.uk/ — sets ci_session /
     fcc_session_cookie cookies and carries a hidden CSRF field
     ``fcc_session_token`` in the ``#wdshInit`` form.
  2. POST /ajaxprocessor/getcollectiondetails with ``uprn`` + the token
     (X-Requested-With: XMLHttpRequest is required, otherwise the CI backend
     answers "No direct script access allowed").
  3. The JSON reply carries ``binCollections.tile`` — a list of HTML snippets,
     one per service, each with an <h3> service name and text
     "Your next scheduled collection is <b>Wednesday, 30 September 2026</b>".
     Only the next date per service is published, so that is all we emit.

Sibling template: ukbcd_south_hams_district_council (same FCC platform, same
JSON endpoint on a different host); Harborough uses the older HTML
``detail-address`` variant. See pipeline/ports/README.md.

Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "West Devon Borough Council"
DESCRIPTION = "Source for westdevon.gov.uk bin collections (FCC Environment)."
URL = "https://westdevon.fccenvironment.co.uk"
TEST_CASES = {
    "Test_001": {"uprn": "100040391940"},
    "Test_002": {"uprn": "100040403601"},
}

BASE = "https://westdevon.fccenvironment.co.uk"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
}

DATE_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})")


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = str(uprn).strip()

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(
            headers=HEADERS,
            follow_redirects=True,
            timeout=30,
            # Server omits its intermediate certificate; data is public.
            verify=False,
        ) as client:
            r = await client.get(BASE + "/")
            r.raise_for_status()
            m = re.search(r'name="fcc_session_token"\s+value="([^"]+)"', r.text)
            if not m:
                raise ValueError("West Devon: could not find fcc_session_token")
            r = await client.post(
                BASE + "/ajaxprocessor/getcollectiondetails",
                data={"fcc_session_token": m.group(1), "uprn": self._uprn},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": BASE + "/",
                },
            )
            r.raise_for_status()
            data = r.json()

        err = data.get("error") or {}
        tiles = (data.get("binCollections") or {}).get("tile") or []
        if not tiles:
            msg = re.sub(r"<[^>]+>", " ", str(err.get("ErrorMessage", ""))).strip()
            raise ValueError(f"West Devon: no collections for UPRN {self._uprn}: {msg}")

        entries: list[Collection] = []
        seen: set[tuple[date, str]] = set()
        for tile in tiles:
            soup = BeautifulSoup(tile[0], "html.parser")
            for div in soup.find_all("div", class_="collectionDiv"):
                h3 = div.find("h3")
                det = div.find("div", class_="wdshDetWrap")
                if not h3 or not det:
                    continue
                text = det.get_text(" ", strip=True)
                if "next scheduled collection is" not in text:
                    continue
                dm = DATE_RE.search(text.split("next scheduled collection is", 1)[1])
                if not dm:
                    continue
                try:
                    d = datetime.strptime(dm.group(1), "%d %B %Y").date()
                except ValueError:
                    continue
                name = h3.get_text(strip=True)
                key = (d, name)
                if key in seen:
                    continue
                seen.add(key)
                entries.append(Collection(date=d, t=name, icon=None))
        entries.sort(key=lambda c: c.date)
        if not entries:
            raise ValueError(f"West Devon: could not parse dates for {self._uprn}")
        return entries
