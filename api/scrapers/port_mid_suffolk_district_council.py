"""Mid Suffolk District Council bin collections (Placecube/Liferay backend).

Per-LAD port of the shared Babergh & Mid Suffolk service. The upstream HACS
source (hacs_babergh_midsuffolk_gov_uk) takes a required ``council`` selector
param, which collides with this API's reserved ``council`` query key (the
scraper id), so it can never be invoked through /lookup. This port hardcodes
the Mid Suffolk backend; Babergh lives in port_babergh_district_council.

Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

import logging
import re
import time
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.curl_cffi_fallback import AsyncClient as _CurlCffiClient
from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentNotFound

TITLE = "Mid Suffolk District Council"
DESCRIPTION = "Source for midsuffolk.gov.uk bin collections."
URL = "https://www.midsuffolk.gov.uk/check-your-collection-day"
TEST_CASES = {
    "Test_001": {"uprn": "100091488908"},
}

ICON_MAP = {
    "Refuse Collection": Icons.GENERAL_WASTE,
    "Recycling Collection": Icons.RECYCLING,
    "Garden Waste Collection": Icons.GARDEN,
    "Food Waste Collection": Icons.BIO_KITCHEN,
    "Paper And Card Collection": Icons.PAPER,
}

_LOGGER = logging.getLogger(__name__)

_BASE_URL = "https://www.midsuffolk.gov.uk"

_NS = "_com_placecube_digitalplace_local_waste_portlet_CollectionDayFinderPortlet_"
_PORTLET_ID = (
    "com_placecube_digitalplace_local_waste_portlet_CollectionDayFinderPortlet"
)


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = str(uprn).strip()

    async def fetch(self) -> list[Collection]:
        try:
            session = _CurlCffiClient(follow_redirects=True)
        except ImportError:
            session = httpx.AsyncClient(follow_redirects=True)
            session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                }
            )

        page_url = f"{_BASE_URL}/check-your-collection-day"

        # Seed the session and retrieve a CSRF token
        r1 = await session.get(page_url, timeout=30)
        r1.raise_for_status()

        auth_match = re.search(r"authToken = '([^']+)'", r1.text)
        p_auth = auth_match.group(1) if auth_match else ""

        post_url = (
            f"{page_url}"
            f"?p_p_id={_PORTLET_ID}"
            f"&p_p_lifecycle=0"
            f"&p_p_state=normal"
            f"&p_p_mode=view"
            f"&{_NS}mvcRenderCommandName=%2Fcollection_day_finder%2Fget_days"
        )

        payload = {
            f"{_NS}formDate": str(int(time.time() * 1000)),
            f"{_NS}postcode": "",
            f"{_NS}uprn": self._uprn,
            f"{_NS}fullAddress": "",
        }

        headers = {
            "Origin": _BASE_URL,
            "Referer": page_url,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-Token": p_auth,
        }

        r2 = await session.post(post_url, data=payload, headers=headers, timeout=30)
        r2.raise_for_status()

        return self._parse(r2.text)

    def _parse(self, html: str) -> list[Collection]:
        soup = BeautifulSoup(html, "html.parser")

        portlet_div = soup.find("div", id=f"p_p_id_{_PORTLET_ID}_")
        if portlet_div:
            h3 = portlet_div.find("h3")
            if h3 and "unable to find" in h3.get_text().lower():
                raise SourceArgumentNotFound(
                    "uprn",
                    self._uprn,
                )

        table = soup.find("table", class_="table")
        if not table:
            raise SourceArgumentNotFound(
                "uprn",
                self._uprn,
            )

        tbody = table.find("tbody")
        if not tbody:
            return []

        entries: list[Collection] = []
        for row in tbody.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) < 2:
                continue

            waste_type = cols[0]
            date_str = " ".join(cols[1].split())

            if not date_str:
                continue

            dt = None
            for fmt in ("%A %d %b %Y", "%d %b %Y"):
                try:
                    dt = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue

            if dt is None:
                _LOGGER.warning("Could not parse date: %r", date_str)
                continue

            icon = next(
                (
                    icon_val
                    for key, icon_val in ICON_MAP.items()
                    if key.lower() in waste_type.lower()
                ),
                None,
            )
            entries.append(Collection(date=dt, t=waste_type, icon=icon))

        return entries
