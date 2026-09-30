"""Mid Suffolk: submit a UPRN to the Placecube/Liferay collection-day portlet."""

from __future__ import annotations

import re
import time
from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    soup,
)

_BASE_URL = "https://www.midsuffolk.gov.uk"
_PAGE_URL = f"{_BASE_URL}/check-your-collection-day"
_NS = "_com_placecube_digitalplace_local_waste_portlet_CollectionDayFinderPortlet_"
_PORTLET_ID = "com_placecube_digitalplace_local_waste_portlet_CollectionDayFinderPortlet"


def _parse(html: str, uprn: str) -> list[Collection]:
    page = soup(html)

    portlet_div = page.find("div", id=f"p_p_id_{_PORTLET_ID}_")
    if portlet_div:
        h3 = portlet_div.find("h3")
        if h3 and "unable to find" in h3.get_text().lower():
            raise AddressNotFound(f"No collection schedule found for UPRN {uprn}")

    table = page.find("table", class_="table")
    if not table:
        raise AddressNotFound(f"No collection schedule found for UPRN {uprn}")

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

        day = None
        for fmt in ("%A %d %b %Y", "%d %b %Y"):
            try:
                day = datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                continue

        if day is not None:
            entries.append(Collection(day, waste_type))

    return entries


class MidSuffolk(Scraper):
    meta = Meta(
        title="Mid Suffolk District Council",
        url="https://www.midsuffolk.gov.uk/check-your-collection-day",
        lads=("E07000203",),
        cases={"Test_001": {"uprn": "100091488908"}},
    )
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        # Seed the session and retrieve a CSRF token.
        r1 = await http.get(_PAGE_URL, timeout=30)
        auth_match = re.search(r"authToken = '([^']+)'", r1.text)
        p_auth = auth_match.group(1) if auth_match else ""

        post_url = (
            f"{_PAGE_URL}"
            f"?p_p_id={_PORTLET_ID}"
            f"&p_p_lifecycle=0"
            f"&p_p_state=normal"
            f"&p_p_mode=view"
            f"&{_NS}mvcRenderCommandName=%2Fcollection_day_finder%2Fget_days"
        )
        payload = {
            f"{_NS}formDate": str(int(time.time() * 1000)),
            f"{_NS}postcode": "",
            f"{_NS}uprn": uprn,
            f"{_NS}fullAddress": "",
        }
        headers = {
            "Origin": _BASE_URL,
            "Referer": _PAGE_URL,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-Token": p_auth,
        }

        r2 = await http.post(post_url, data=payload, headers=headers, timeout=30)
        return _parse(r2.text, uprn)


SCRAPER = MidSuffolk()
