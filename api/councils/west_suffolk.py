"""West Suffolk: looks up an address by UPRN and reads collection dates from its MyWestSuffolk page."""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import Tag
from dateutil.parser import parse as date_parse

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_URL = "https://maps.westsuffolk.gov.uk/MyWestSuffolk.aspx"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    )
}


def _panel_search(cur_tag: Tag) -> bool:
    if cur_tag.name != "div":
        return False

    tag_class = cur_tag.attrs.get("class")
    if tag_class is None:
        return False

    parent_has_header = cur_tag.parent.find_all(
        "h4", string=lambda text: text and "Bin collection days" in text
    )
    if len(parent_has_header) < 1:
        return False

    return "atPanelData" in tag_class


class WestSuffolk(Scraper):
    meta = Meta(
        title="West Suffolk",
        url=_URL,
        lads=("E07000245",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        user_uprn = address.need("uprn")
        api_url = f"{_URL}?action=SetAddress&UniqueId={user_uprn}"
        response = await http.get(api_url, headers=_HEADERS)

        page = soup(response.text)
        collection_tags = page.body.find_all(_panel_search)

        collections: list[Collection] = []
        for tag in collection_tags:
            text_list = [text.strip() for text in tag.stripped_strings if text.strip()]
            if len(text_list) % 2 != 0:
                text_list = text_list[:-1]

            for index in range(0, len(text_list), 2):
                bin_name, collection_date = text_list[index:index + 2]
                try:
                    bin_name_clean = (
                        bin_name.strip()
                        .replace("\r", "")
                        .replace("\n", "")
                        .replace(":", "")
                    )
                    bin_name_clean = re.sub(" +", " ", bin_name_clean)

                    # Keep the council's existing date handling: use the parsed
                    # month and day, but replace the year with the current year.
                    next_collection = date_parse(collection_date).replace(year=datetime.now().year)
                    collections.append(
                        Collection(next_collection.date(), bin_name_clean)
                    )
                except ValueError as exc:
                    raise UpstreamError(f"West Suffolk: error parsing bin data: {exc}") from exc

        return collections


SCRAPER = WestSuffolk()
