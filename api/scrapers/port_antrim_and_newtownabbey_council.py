import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from api.compat.address import first_line
from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentExceptionMultiple

TITLE = "Antrim and Newtownabbey"
DESCRIPTION = "Source for Antrim and Newtownabbey bin collection schedule (address ID lookup)."
URL = "https://antrimandnewtownabbey.gov.uk/residents/bins-recycling/bins-schedule/"
TEST_CASES = {
    "Test_001": {"id": 1456},
    "Test_002": {"id": "1145"},
    "Postcode + address": {"postcode": "BT41 2LG", "address": "59 Thornhill Road"},
}

API_URL = "https://antrimandnewtownabbey.gov.uk/residents/bins-recycling/bins-schedule/"

ICON_MAP = {
    "Black bins": Icons.GENERAL_WASTE,
    "Brown bins": Icons.BIO_KITCHEN,
    "Kerbside Recycling": Icons.RECYCLING,
}

# Kentico WebPart fields on the schedule page: a postcode search fills a
# dropdown whose option values are the address IDs used by `?Id=`.
_LOOKUP = "p$lt$ctl07$pageplaceholder$p$lt$ctl02$BinCollectionLookup$"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


class Source:
    def __init__(
        self,
        id: int | str | None = None,
        postcode: str = "",
        address: str = "",
        house_number: str = "",
        street: str = "",
    ):
        self._id = str(id) if id is not None else None
        self._postcode = (postcode or "").strip().upper()
        self._address = first_line(address, house_number, street)

    async def _lookup_id(self, s: httpx.AsyncClient) -> str:
        """Search the council's postcode form and pick the address ID."""
        r = await s.get(API_URL)
        r.raise_for_status()
        form = BeautifulSoup(r.text, "html.parser").find("form", id="form")
        if form is None:
            raise ValueError("Antrim and Newtownabbey bin search form not found")
        data = {
            i["name"]: i.get("value", "")
            for i in form.find_all("input", type="hidden")
            if i.get("name")
        }
        data[_LOOKUP + "txtBinSearch"] = self._postcode
        data[_LOOKUP + "btnBinSearch"] = "Search"
        r = await s.post(API_URL, data=data)
        r.raise_for_status()
        options = [
            (o.get_text(" ", strip=True), o["value"])
            for o in BeautifulSoup(r.text, "html.parser").select(
                'select[id$="ddlAddress"] option'
            )
            if o.get("value")
        ]
        if not options:
            raise ValueError(f"No addresses found for postcode {self._postcode}")
        want = " ".join(re.sub(r"[^A-Z0-9 ]", " ", self._address.upper()).split())
        for text, value in options:
            norm = " ".join(re.sub(r"[^A-Z0-9 ]", " ", text.upper()).split())
            if want and (norm == want or norm.startswith(want + " ")):
                return value
        raise ValueError(
            f"Address {self._address!r} not found for {self._postcode}; options: "
            + "; ".join(t for t, _ in options[:10])
        )

    async def fetch(self) -> list[Collection]:
        if self._id is None and not (self._postcode and self._address):
            raise SourceArgumentExceptionMultiple(
                ["id"],
                "An id (address ID from the council bin schedule page) "
                "or a postcode and address is required",
            )

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=30.0, headers=HEADERS
        ) as s:
            if self._id is None:
                self._id = await self._lookup_id(s)
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
