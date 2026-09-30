from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentExceptionMultiple

TITLE = "Antrim and Newtownabbey"
DESCRIPTION = "Source for Antrim and Newtownabbey bin collection schedule (address ID lookup)."
URL = "https://antrimandnewtownabbey.gov.uk/residents/bins-recycling/bins-schedule/"
TEST_CASES = {
    "Test_001": {"id": 1456},
    "Test_002": {"id": "1145"},
}

API_URL = "https://antrimandnewtownabbey.gov.uk/residents/bins-recycling/bins-schedule/"

ICON_MAP = {
    "Black bins": Icons.GENERAL_WASTE,
    "Brown bins": Icons.BIO_KITCHEN,
    "Kerbside Recycling": Icons.RECYCLING,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


class Source:
    def __init__(self, id: int | str | None = None):
        self._id = str(id) if id is not None else None

    async def fetch(self) -> list[Collection]:
        if self._id is None:
            raise SourceArgumentExceptionMultiple(
                ["id"], "An id (address ID from the council bin schedule page) is required"
            )

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=30.0, headers=HEADERS
        ) as s:
            r = await s.get(API_URL, params={"Id": self._id, "size": 20})
            r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        collection_divs = soup.select("div.feature-box.bins")
        if not collection_divs:
            raise SourceArgumentExceptionMultiple(
                ["id"], "No collections found"
            )

        entries = []
        for collection_div in collection_divs:
            date_p = collection_div.select_one("p.date")
            if not date_p:
                continue

            # Thu 22 Aug, 2024
            try:
                date_ = datetime.strptime(date_p.text.strip(), "%a %d %b, %Y").date()
            except ValueError:
                continue
            bins = collection_div.select("li")
            if not bins:
                continue
            for bin in bins:
                if not bin.text.strip():
                    continue
                bin_type = bin.text.strip()
                icon = ICON_MAP.get(bin_type)
                entries.append(Collection(date=date_, t=bin_type, icon=icon))
        return entries
