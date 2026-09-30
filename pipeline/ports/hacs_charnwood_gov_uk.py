from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup
from dateutil.parser import parse

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import (
    SourceArgumentNotFound,
    SourceArgumentNotFoundWithSuggestions,
)

TITLE = "Charnwood"
DESCRIPTION = "Source for Charnwood."
URL = "https://www.charnwood.gov.uk/"
TEST_CASES = {
    "111, Main Street, Swithland": {"address": "111, Main Street, Swithland"},
    "2, The Banks, Sileby": {"address": "2 The Banks, Sileby"},
}


ICON_MAP = {
    "Refuse": Icons.GENERAL_WASTE,
    "Garden Waste": Icons.GARDEN,
    "Recycling": Icons.RECYCLING,
}


API_URL = "https://my.charnwood.gov.uk/my-property-finder"
SEARCH_URL = "https://my.charnwood.gov.uk/data/ac/addresses.json"


def _norm(text: str) -> str:
    return text.lower().replace(" ", "").replace(",", "")


class Source:
    def __init__(
        self,
        address: str = "",
        house_number: str = "",
        street: str = "",
        postcode: str = "",
        uprn: str = "",
    ):
        self._uprn = str(uprn).strip() if uprn else ""
        self._postcode = postcode.strip() if postcode else ""
        if house_number and street:
            address = f"{house_number}, {street}"
        if not (address or self._postcode and self._uprn):
            raise SourceArgumentNotFound("address", address)
        self._address_search: str = address or self._postcode
        self._address_compare: str = _norm(address)
        self._address_id = None

    def _match_address(self, address: str) -> bool:
        # Council labels are "<number>, <street>, <town>" with no postcode, so
        # accept a label equal to, or a prefix of, the supplied address.
        label = _norm(address)
        return label == self._address_compare or (
            bool(self._address_compare) and self._address_compare.startswith(label)
        )

    @staticmethod
    def _parse_date(date_str: str) -> date:
        if date_str.lower() == "today":
            return date.today()

        if date_str.lower() == "tomorrow":
            return date.today() + timedelta(days=1)

        return parse(date_str).date()

    async def _get_address_id(self):
        # Address ids are "cbc" + UPRN; prefer that exact match when we have a
        # UPRN, searching by postcode (which the search endpoint supports).
        params = {
            "term": self._postcode if self._uprn and self._postcode else self._address_search,
        }
        r = await httpx.AsyncClient(follow_redirects=True).get(SEARCH_URL, params=params)
        r.raise_for_status()
        data = r.json()
        if not data:
            raise SourceArgumentNotFound(
                "address",
                self._address_search,
            )

        if self._uprn:
            for address in data:
                if address["value"] == f"cbc{self._uprn}":
                    self._address_id = address["value"]
                    return

        for address in data:
            if self._match_address(address["label"]):
                self._address_id = address["value"]
                return
        raise SourceArgumentNotFoundWithSuggestions(
            "address", self._address_search, [address["label"] for address in data]
        )

    async def fetch(self) -> list[Collection]:
        fresh_id = False
        if not self._address_id:
            await self._get_address_id()
            fresh_id = True

        try:
            return await self._get_collections()
        except Exception:
            if fresh_id:
                raise
            await self._get_address_id()
            return await self._get_collections()

    async def _get_collections(self) -> list[Collection]:
        if not self._address_id:
            raise ValueError("Address not set")

        args = {"address_id": self._address_id}

        # get json file
        r = await httpx.AsyncClient(follow_redirects=True).get(API_URL, params=args)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        collection_panel = soup.find("div", {"class": "refusecollectiondates"})
        if not collection_panel:
            raise ValueError("No collection panel found")
        entries = []

        for li in collection_panel.select("li"):
            date_tag = li.find("strong")
            if not date_tag:
                continue
            date_str = date_tag.text.strip()
            waste_type_tag = date_tag.find_next("a")
            if not waste_type_tag:
                continue
            waste_type = waste_type_tag.text.strip()
            date_ = self._parse_date(date_str)
            entries.append(Collection(date_, waste_type, icon=ICON_MAP.get(waste_type)))

        return entries
