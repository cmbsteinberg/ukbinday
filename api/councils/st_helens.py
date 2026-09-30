"""St Helens: submit a postcode, then its UPRN, to retrieve the collection table."""

from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup, Tag

from api.councils._base import Address, Collection, Http, Meta, Scraper, Transport, soup

_PAGE = "https://www.sthelens.gov.uk/article/3473/Check-your-collection-dates"
_PROCESS = "https://www.sthelens.gov.uk/apiserver/formsservice/http/processsubmission"
_WASTE_TYPE_MAP = {
    "general non-recyclable waste": "General Waste",
    "recycling": "Recycling",
    "garden waste": "Garden Waste",
}


def _input_value(page: BeautifulSoup, field_name: str) -> str:
    input_field = page.find("input", {"name": field_name})
    if not isinstance(input_field, Tag):
        return ""
    value = input_field.get("value")
    return str(value) if value else ""


def _parse_collections(table: Tag) -> list[Collection]:
    collections: list[Collection] = []
    current_month: str | None = None
    current_year: str | None = None

    for row in table.find_all("tr"):
        header = row.find("th", {"scope": "row"})
        if isinstance(header, Tag):
            month_year = header.get_text(strip=True).split()
            if len(month_year) == 2:
                current_month, current_year = month_year
            continue

        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        day = cells[0].get_text(strip=True)
        waste_description = cells[3].get_text(strip=True)
        if not (current_month and current_year and day):
            continue

        try:
            waste_date = datetime.strptime(
                f"{day} {current_month} {current_year}", "%d %B %Y"
            ).date()
        except ValueError:
            continue

        for waste_type in waste_description.split("&"):
            waste_type = waste_type.strip()
            if " ".join(waste_type.split()).casefold() in _WASTE_TYPE_MAP:
                collections.append(Collection(waste_date, waste_type))

    return collections


class StHelens(Scraper):
    meta = Meta(
        title="St Helens Council",
        url="https://sthelens.gov.uk",
        lads=("E08000013",),
        cases={
            "Test_001": {"postcode": "WA10 1HE", "uprn": "39079361"},
            "Test_002": {"postcode": "WA10 1TG", "uprn": "39013329"},
            "Test_003": {"postcode": "WA10 9TJ", "uprn": "39060317"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").strip().upper()
        uprn = address.need("uprn")

        response = await http.get(_PAGE, timeout=30)
        page = soup(response.text)

        page_session_id = _input_value(page, "RESIDENTCOLLECTIONDATES_PAGESESSIONID")
        session_id = _input_value(page, "RESIDENTCOLLECTIONDATES_SESSIONID")
        nonce = _input_value(page, "RESIDENTCOLLECTIONDATES_NONCE")

        payload = {
            "RESIDENTCOLLECTIONDATES_PAGESESSIONID": page_session_id,
            "RESIDENTCOLLECTIONDATES_SESSIONID": session_id,
            "RESIDENTCOLLECTIONDATES_NONCE": nonce,
            "RESIDENTCOLLECTIONDATES_VARIABLES": "e30%3D",
            "RESIDENTCOLLECTIONDATES_PAGENAME": "PAGE1",
            "RESIDENTCOLLECTIONDATES_PAGEINSTANCE": 0,
            "RESIDENTCOLLECTIONDATES_PAGE1_NOADDRESSESLAYOUT": True,
            "RESIDENTCOLLECTIONDATES_PAGE1_POSTCODE": postcode,
            "RESIDENTCOLLECTIONDATES_FORMACTION_NEXT": "RESIDENTCOLLECTIONDATES_PAGE1_FINDADDRESS",
            "RESIDENTCOLLECTIONDATES_PAGE1_ADDRESSESLAYOUT": False,
        }
        url = (
            f"{_PROCESS}?pageSessionId={page_session_id}"
            f"&fsid={session_id}&fsn={nonce}"
        )
        response = await http.post(url, data=payload, timeout=30)
        page = soup(response.text)
        nonce = _input_value(page, "RESIDENTCOLLECTIONDATES_NONCE")

        payload = {
            "RESIDENTCOLLECTIONDATES_PAGESESSIONID": page_session_id,
            "RESIDENTCOLLECTIONDATES_SESSIONID": session_id,
            "RESIDENTCOLLECTIONDATES_NONCE": nonce,
            "RESIDENTCOLLECTIONDATES_VARIABLES": "e30%3D",
            "RESIDENTCOLLECTIONDATES_PAGENAME": "PAGE1",
            "RESIDENTCOLLECTIONDATES_PAGEINSTANCE": 1,
            "RESIDENTCOLLECTIONDATES_PAGE1_NOADDRESSESLAYOUT": False,
            "RESIDENTCOLLECTIONDATES_PAGE1_ADDRESSESLAYOUT": True,
            "RESIDENTCOLLECTIONDATES_PAGE1_ADDRESS": uprn,
            "RESIDENTCOLLECTIONDATES_FORMACTION_NEXT": "RESIDENTCOLLECTIONDATES_PAGE1_ADDRESSNEXT",
        }
        url = (
            f"{_PROCESS}?pageSessionId={page_session_id}"
            f"&fsid={session_id}&fsn={nonce}"
        )
        response = await http.post(url, data=payload)
        page = soup(response.text)

        table = page.find("table")
        if not isinstance(table, Tag):
            return []
        return _parse_collections(table)


SCRAPER = StHelens()
