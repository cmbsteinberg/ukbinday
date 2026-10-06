"""Wigan: search by postcode, then select the address by its UPRN on MyNeighbourhood."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    find_tag,
    soup,
)

_PAGE = "https://apps.wigan.gov.uk/MyNeighbourhood/"
_ORDINALS = re.compile(r"(st|nd|rd|th)")


def _asp_var(page: object, field: str) -> str:
    node = page.find("input", {"id": field})
    value = node.get("value") if node is not None else None
    if not isinstance(value, str):
        raise UpstreamError(f"Wigan page is missing ASP variable {field}")
    return value


class Wigan(Scraper):
    meta = Meta(
        title="Wigan Council",
        url="https://wigan.gov.uk",
        lads=("E08000010",),
        cases={
            "Test_001": {"postcode": "WN5 9BH", "uprn": "100011821616"},
            "Test_002": {"postcode": "WN6 8RG", "uprn": "100011776859"},
            "Test_003": {"postcode": "WN3 6AU", "uprn": "100011749007"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").upper()
        uprn = address.need("uprn").zfill(12)

        r0 = await http.get(_PAGE)
        page = soup(r0.text)

        payload = {
            "__VIEWSTATE": _asp_var(page, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": _asp_var(page, "__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": _asp_var(page, "__EVENTVALIDATION"),
            "ctl00$ContentPlaceHolder1$txtPostcode": postcode,
            "ctl00$ContentPlaceHolder1$btnPostcodeSearch": "Search",
        }

        r1 = await http.post(_PAGE, data=payload)
        page = soup(r1.text)

        payload = {
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$lstAddresses",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "__VIEWSTATE": _asp_var(page, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": _asp_var(page, "__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": _asp_var(page, "__EVENTVALIDATION"),
            "ctl00$ContentPlaceHolder1$txtPostcode": postcode,
            "ctl00$ContentPlaceHolder1$lstAddresses": "UPRN" + uprn,
        }

        r2 = await http.post(_PAGE, data=payload)
        page = soup(r2.text)

        collections = []
        for bin_node in page.find_all("div", {"class": "BinsRecycling"}):
            waste_type = find_tag(bin_node, "h2").text
            waste_date = find_tag(bin_node, "div", {"class": "dateWrapper-next"}).get_text(
                strip=True
            )
            waste_date = _ORDINALS.sub("", waste_date.split("day")[1])
            day = datetime.strptime(waste_date, "%d%b%Y").date()
            collections.append(Collection(day, waste_type))

        return collections


SCRAPER = Wigan()
