"""Placecube DigitalPlace "check your collection day" portlet (Liferay), used by Babergh and Mid Suffolk.

Both sites run `CollectionDayFinderPortlet`:

1. `GET <site>/check-your-collection-day` seeds the session; the page carries the
   Liferay CSRF token as `authToken = '...'`.
2. `POST` the portlet's `get_days` render command with the UPRN. The answer is a
   page whose `table.table` lists `[service, date]` rows; "unable to find" in the
   portlet's `<h3>` (or no table) means the UPRN is unknown.

What differs per council is the site, in `PlacecubeConfig`.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Platform,
    Transport,
    UpstreamError,
    parse_date,
    soup,
)

_PORTLET_ID = "com_placecube_digitalplace_local_waste_portlet_CollectionDayFinderPortlet"
_NS = f"_{_PORTLET_ID}_"
_TOKEN = re.compile(r"authToken = '([^']+)'")
_TIMEOUT = 30


@dataclass(frozen=True, slots=True, kw_only=True)
class PlacecubeConfig:
    base_url: str
    """No trailing slash: "https://babergh.gov.uk"."""
    page_path: str = "/check-your-collection-day"


class Placecube(Platform[PlacecubeConfig]):
    requires = frozenset({"uprn"})
    transport = Transport.CURL_CFFI

    def _parse(self, html: str, uprn: str) -> list[Collection]:
        page = soup(html)
        not_found = AddressNotFound(f"{self.meta.title} has no collection schedule for UPRN {uprn}")

        portlet = page.find("div", id=f"p_p_id_{_PORTLET_ID}_")
        if portlet:
            h3 = portlet.find("h3")
            if h3 and "unable to find" in h3.get_text().lower():
                raise not_found

        table = page.find("table", class_="table")
        if not table:
            raise not_found
        tbody = table.find("tbody")
        if not tbody:
            raise UpstreamError(f"{self.meta.title} schedule table has no body")

        entries: list[Collection] = []
        for row in tbody.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) < 2:
                continue
            date_text = " ".join(cols[1].split())
            if not date_text:
                continue
            entries.append(Collection(parse_date(date_text), cols[0]))
        return entries

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        base_url = self.config.base_url
        page_url = f"{base_url}{self.config.page_path}"

        page = await http.get(page_url, timeout=_TIMEOUT)
        token = _TOKEN.search(page.text)
        csrf = token.group(1) if token else ""

        post_url = (
            f"{page_url}?p_p_id={_PORTLET_ID}&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
            f"&{_NS}mvcRenderCommandName=%2Fcollection_day_finder%2Fget_days"
        )
        payload = {
            f"{_NS}formDate": str(int(time.time() * 1000)),
            f"{_NS}postcode": "",
            f"{_NS}uprn": uprn,
            f"{_NS}fullAddress": "",
        }
        headers = {
            "Origin": base_url,
            "Referer": page_url,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-Token": csrf,
        }
        r = await http.post(post_url, data=payload, headers=headers, timeout=_TIMEOUT)
        return self._parse(r.text, uprn)
