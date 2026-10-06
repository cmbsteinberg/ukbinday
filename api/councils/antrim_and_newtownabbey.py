"""Antrim and Newtownabbey: postcode search selects an address ID for the bin schedule page."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    find_tag,
    match_address,
    soup,
    text_of,
)

_PAGE = "https://antrimandnewtownabbey.gov.uk/residents/bins-recycling/bins-schedule/"
_LOOKUP = "p$lt$ctl07$pageplaceholder$p$lt$ctl02$BinCollectionLookup$"


class AntrimAndNewtownabbey(Scraper):
    meta = Meta(
        title="Antrim and Newtownabbey",
        url=_PAGE,
        lads=("N09000001",),
        cases={
            "Test_001": {"id": "1456"},
            "Test_002": {"id": "1145"},
            "Postcode + address": {
                "postcode": "BT41 2LG",
                "house_number": "59",
                "street": "Thornhill Road",
            },
        },
    )
    requires = frozenset()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        )
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        address_id = address.get("id")
        if address_id is None:
            if address.postcode is None or address.first_line is None:
                raise InputError("An id or a postcode and address is required")

            r = await http.get(_PAGE, timeout=30.0)
            form = find_tag(soup(r.text), "form", id="form", what="Antrim and Newtownabbey bin search form not found")

            data = {
                item["name"]: item.get("value", "")
                for item in form.find_all("input", type="hidden")
                if item.get("name")
            }
            data[_LOOKUP + "txtBinSearch"] = address.postcode
            data[_LOOKUP + "btnBinSearch"] = "Search"

            r = await http.post(_PAGE, data=data, timeout=30.0)
            options = [
                option
                for option in soup(r.text).select('select[id$="ddlAddress"] option')
                if option.get("value")
            ]
            address_id = match_address(
                address,
                options,
                text=text_of,
            )["value"]

        r = await http.get(_PAGE, params={"Id": address_id, "size": 20}, timeout=30.0)
        page = soup(r.text)
        collection_divs = page.select("div.feature-box.bins")
        if not collection_divs:
            raise InputError("No collections found")

        collections = []
        for collection_div in collection_divs:
            date_p = collection_div.select_one("p.date")
            if not date_p:
                continue
            try:
                collection_date = datetime.strptime(
                    text_of(date_p), "%a %d %b, %Y"
                ).date()
            except ValueError:
                continue

            for bin_item in collection_div.select("li"):
                bin_type = text_of(bin_item)
                if bin_type:
                    collections.append(Collection(collection_date, bin_type))

        return collections


SCRAPER = AntrimAndNewtownabbey()
