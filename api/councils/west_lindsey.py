"""West Lindsey: search the postcode and house number, then fetch the property's bin schedule."""

from __future__ import annotations

import json
import re
import urllib.parse

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    find_tag,
    parse_date,
    soup,
)

_STAGE1_URL = (
    "https://wlnk.statmap.co.uk/map/Cluster.svc/findLocation"
    "?callback=getAddressesCallback1702938375023"
    "&script=%5CCluster%5CCluster.AuroraScript%24&address={}"
)
_STAGE2_URL = (
    r"https://wlnk.statmap.co.uk/map/Cluster.svc/getpage"
    r"?script=\Cluster\Cluster.AuroraScript$&taskId=bins&format=js"
    r"&updateOnly=true&query=x%3D{x}%3By%3D{y}%3Bid%3D{id}"
)
_JSONP_PREFIX = re.compile(r"getAddressesCallback\d+\(")
_BIN_HTML = re.compile(r'document\.getElementById\("DR1"\)\.innerHTML="(.+)";')
_BIN_DATE = re.compile(r"\d+/\d+")


class WestLindsey(Scraper):
    meta = Meta(
        title="West Lindsey",
        url="https://www.west-lindsey.gov.uk/",
        lads=("E07000142",),
        cases={},
    )
    requires = frozenset({"postcode", "house_number"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        user_address = urllib.parse.quote(
            f"{address.need('house_number')} {address.need('postcode')}"
        )
        stage1_url = _STAGE1_URL.format(user_address)
        address_response = await http.get(stage1_url)

        try:
            address_data = json.loads(_JSONP_PREFIX.sub("", address_response.text)[:-2])
            total_hits = address_data["TotalHits"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise UpstreamError("West Lindsey returned an invalid address response") from exc

        if total_hits == 0:
            raise AddressNotFound(f"No address found for string {user_address}")

        try:
            location = address_data["Locations"][0]
            address_id = location["Id"]
            address_x = location["X"]
            address_y = location["Y"]
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("West Lindsey returned no usable address location") from exc

        stage2_url = _STAGE2_URL.format(x=address_x, y=address_y, id=address_id)
        bin_query = (await http.get(stage2_url)).text

        if "injectCss" not in bin_query:
            raise UpstreamError("West Lindsey returned an invalid bin schedule response")

        bin_html = _BIN_HTML.findall(bin_query)
        if len(bin_html) != 1:
            raise UpstreamError("West Lindsey returned an unexpected bin schedule response")

        try:
            html = bin_html[0].encode().decode("unicode-escape")
        except UnicodeDecodeError as exc:
            raise UpstreamError("West Lindsey returned invalid schedule HTML") from exc

        page = soup(html)
        listing = find_tag(page, "li", class_="auroraListItem", what="West Lindsey's schedule contains no collection list")

        collections: list[Collection] = []
        for row in listing.find_all("li"):
            bin_name = find_tag(row, "span", what="West Lindsey's schedule contains a row with no bin type")
            bin_type = bin_name.text.title()

            for bin_date in _BIN_DATE.findall(row.text):
                try:
                    collection_date = parse_date(bin_date)
                except ValueError:
                    continue
                collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = WestLindsey()
