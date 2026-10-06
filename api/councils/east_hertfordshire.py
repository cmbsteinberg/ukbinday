"""East Herts: an AchieveForms lookup by UPRN, with a postcode search fallback."""

from __future__ import annotations

import re

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
    soup,
    text_of,
)
from api.councils._platforms.achieveforms import first_row, run_lookup

_SERVICE_URL = (
    "https://eastherts-self.achieveservice.com/service/"
    "Bins___When_are_my_Bin_Collection_days"
)
_API_URL = "https://eastherts-self.achieveservice.com/apibroker/runLookup"
_UPRN_URL = "https://uprn.uk/postcode/{postcode}"
_HEADERS = {"user-agent": "Mozilla/5.0"}
_SID_PATTERN = r"sid=(.+)"


async def _get_uprn_from_postcode(http: Http, postcode: str) -> str:
    """Return the first UPRN listed for a postcode."""
    response = await http.get(_UPRN_URL.format(postcode=postcode.replace(" ", "")))
    page = soup(response.text)
    container = page.find("div", {"class": "threecol"})
    item = container.find("li") if container else None
    link = item.find("a", href=True) if item else None
    uprn = text_of(link)
    if not uprn:
        raise AddressNotFound(f"No UPRN found for postcode {postcode}")
    return uprn


class EastHertfordshire(Scraper):
    meta = Meta(
        title="East Herts Council",
        url="https://www.eastherts.gov.uk",
        lads=("E07000242",),
        cases={
            "Example": {"postcode": "SG9 9AA", "house_number": "1"},
            "UPRN only": {"uprn": "100080738904"},
            "UPRN, postcode & number": {
                "uprn": "10033104539",
                "postcode": "SG9 9AA",
                "house_number": "1",
            },
        },
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if uprn is None:
            if address.postcode is None:
                raise InputError("East Herts needs a UPRN or a postcode")
            uprn = await _get_uprn_from_postcode(http, address.postcode)

        response = await http.get(_SERVICE_URL, headers=_HEADERS)
        page = soup(response.text)
        sid: str | None = None
        for link in page.find_all("link", href=True):
            href = link.get("href", "")
            if "apibroker" in href:
                matches = re.findall(_SID_PATTERN, href)
                if matches:
                    sid = matches[0]
                    break
        if sid is None:
            raise UpstreamError("East Herts page did not provide an API session ID")

        rowdata = first_row(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "683d9ff0e299d",
                {"Collection Days": {"inputUPRN": {"value": uprn}}},
                no_retry="true",
                headers=_HEADERS,
            )
        )
        if rowdata is None:
            raise AddressNotFound(f"East Herts has no collection data for UPRN {uprn}")

        dates = {}
        for item in rowdata:
            if "NextDate" in item and rowdata[item] != "":
                dates[item.replace("NextDate", "")] = parse_date(rowdata[item])

        collections = []
        for item, day in dates.items():
            bin_type = "Garden Waste" if item == "GW" else item
            collections.append(Collection(day, bin_type))
        return collections


SCRAPER = EastHertfordshire()
