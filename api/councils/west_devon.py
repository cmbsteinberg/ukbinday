"""West Devon: fetches FCC Environment collection details using a session token and UPRN."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

BASE = "https://westdevon.fccenvironment.co.uk"
_DATE_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})")


class WestDevon(Scraper):
    meta = Meta(
        title="West Devon Borough Council",
        url=BASE,
        lads=("E07000047",),
        cases={
            "Test_001": {"uprn": "100040391940"},
            "Test_002": {"uprn": "100040403601"},
        },
    )
    requires = frozenset({"uprn"})
    # No browser User-Agent: the CDN 403s a bare Chrome UA from datacentre IPs
    # (Harborough, same platform, works from Vercel with httpx's default).
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        r = await http.get(BASE + "/")
        token_match = re.search(r'name="fcc_session_token"\s+value="([^"]+)"', r.text)
        if not token_match:
            raise UpstreamError("West Devon: could not find fcc_session_token")

        r = await http.post(
            BASE + "/ajaxprocessor/getcollectiondetails",
            data={"fcc_session_token": token_match.group(1), "uprn": uprn},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": BASE + "/",
            },
        )
        data = r.json()

        error = data.get("error") or {}
        tiles = (data.get("binCollections") or {}).get("tile") or []
        if not tiles:
            message = re.sub(r"<[^>]+>", " ", str(error.get("ErrorMessage", ""))).strip()
            raise InputError(f"West Devon: no collections for UPRN {uprn}: {message}")

        collections: list[Collection] = []
        for tile in tiles:
            for div in soup(tile[0]).find_all("div", class_="collectionDiv"):
                heading = div.find("h3")
                details = div.find("div", class_="wdshDetWrap")
                if not heading or not details:
                    continue
                text = details.get_text(" ", strip=True)
                if "next scheduled collection is" not in text:
                    continue
                date_match = _DATE_RE.search(text.split("next scheduled collection is", 1)[1])
                if not date_match:
                    continue
                try:
                    day = datetime.strptime(date_match.group(1), "%d %B %Y").date()
                except ValueError:
                    continue
                collections.append(Collection(day, heading.get_text(strip=True)))

        if not collections:
            raise UpstreamError(f"West Devon: could not parse dates for {uprn}")
        return collections


SCRAPER = WestDevon()
