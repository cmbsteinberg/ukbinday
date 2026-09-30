"""Babergh District Council: posts a UPRN to its Placecube/Liferay collection-day form."""

from __future__ import annotations

import logging
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

_LOGGER = logging.getLogger(__name__)

_BASE_URL = "https://babergh.gov.uk"
_PAGE_URL = f"{_BASE_URL}/check-your-collection-day"
_NS = "_com_placecube_digitalplace_local_waste_portlet_CollectionDayFinderPortlet_"
_PORTLET_ID = "com_placecube_digitalplace_local_waste_portlet_CollectionDayFinderPortlet"


def _parse(html: str, uprn: str) -> list[Collection]:
    page = soup(html)

    portlet_div = page.find("div", id=f"p_p_id_{_PORTLET_ID}_")
    if portlet_div:
        h3 = portlet_div.find("h3")
        if h3 and "unable to find" in h3.get_text().lower():
            raise AddressNotFound(f"Babergh could not find a collection schedule for UPRN {uprn}")

    table = page.find("table", class_="table")
    if not table:
        raise AddressNotFound(f"Babergh could not find a collection schedule for UPRN {uprn}")

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

        if day is None:
            _LOGGER.warning("Could not parse date: %r", date_str)
            continue

        entries.append(Collection(day, waste_type))

    return entries


class Babergh(Scraper):
    meta = Meta(
        title="Babergh District Council",
        url="https://babergh.gov.uk/check-your-collection-day",
        lads=("E07000200",),
        cases={"Test_001": {"uprn": "100091085564"}},
    )
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        await http.get(_PAGE_URL, timeout=30)

        auth_match = re.search(r"authToken = '([^']+)'", (await http.get(_PAGE_URL, timeout=30)).text)
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

        r = await http.post(post_url, data=payload, headers=headers, timeout=30)
        return _parse(r.text, uprn)


SCRAPER = Babergh()
