"""East Renfrewshire: submit a postcode to the bin-days form, then request results by UPRN."""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

from bs4 import Tag
from dateutil import parser

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

TITLE = "East Renfrewshire Council"
URL = "https://eastrenfrewshire.gov.uk"
FORM_PAGE = f"{URL}/bin-days"


def _form_ids(action: str) -> dict[str, str]:
    query = parse_qs(urlparse(action).query)
    return {
        "page_session_id": query.get("pageSessionId", [""])[0],
        "session_id": query.get("fsid", [""])[0],
        "nonce": query.get("fsn", [""])[0],
    }


def _form_values(form: Tag) -> tuple[str, str, str]:
    def value(name: str) -> str:
        element = form.find("input", attrs={"name": name})
        return str(element["value"]) if isinstance(element, Tag) and element.has_attr("value") else ""

    page_session_id = value("BINDAYSV2_PAGESESSIONID")
    session_id = value("BINDAYSV2_SESSIONID")
    nonce = value("BINDAYSV2_NONCE")
    if not (page_session_id and session_id and nonce):
        action = str(form["action"])
        ids = _form_ids(action)
        page_session_id = page_session_id or ids["page_session_id"]
        session_id = session_id or ids["session_id"]
        nonce = nonce or ids["nonce"]
    return page_session_id, session_id, nonce


def _results(html: str) -> list[Collection]:
    page = soup(html)
    table = find_tag(page, "div", id="BINDAYSV2_RESULTS_NEXTCOLLECTIONLISTV4", what="Could not find bin collection results table.")

    collections: list[Collection] = []
    for row in table.find_all("tr")[1:]:
        columns = row.find_all("td")
        if len(columns) < 3:
            continue

        try:
            collection_date: date = parser.parse(
                columns[0].get_text(strip=True), dayfirst=True
            ).date()
        except (ValueError, OverflowError):
            continue

        for image in columns[2].find_all("img"):
            color = image.get("alt", "").split()[0]
            collections.append(Collection(collection_date, color))

    return collections


class EastRenfrewshire(Scraper):
    meta = Meta(
        title=TITLE,
        url=URL,
        lads=("S12000011",),
        cases={
            "Test_001": {"postcode": "G78 2TJ", "uprn": "131016859"},
            "Test_002": {"postcode": "g775ar", "uprn": "131019331"},
            "Test_003": {"postcode": "g78 3er", "uprn": "000131020112"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        uprn = address.need("uprn").zfill(12)

        response = await http.get(FORM_PAGE, timeout=30)
        page = soup(response.text)
        form = page.find(id="BINDAYSV2_FORM")
        if not isinstance(form, Tag) or not form.has_attr("action"):
            raise UpstreamError(
                "Form with id 'BINDAYSV2_FORM' and 'action' attribute not found on PAGE1."
            )

        action = str(form["action"])
        page_session_id, session_id, nonce = _form_values(form)
        response = await http.post(
            action,
            headers={"Origin": URL, "Referer": FORM_PAGE},
            data={
                "BINDAYSV2_PAGESESSIONID": page_session_id,
                "BINDAYSV2_SESSIONID": session_id,
                "BINDAYSV2_NONCE": nonce,
                "BINDAYSV2_VARIABLES": "e30=",
                "BINDAYSV2_PAGENAME": "PAGE1",
                "BINDAYSV2_PAGEINSTANCE": "0",
                "BINDAYSV2_PAGE1_POSTCODE": postcode,
                "BINDAYSV2_FORMACTION_NEXT": "BINDAYSV2_PAGE1_FIELD290",
            },
            timeout=30,
        )

        page = soup(response.text)
        form = page.find(id="BINDAYSV2_FORM")
        if not isinstance(form, Tag) or not form.has_attr("action"):
            raise UpstreamError(
                "Form with id 'BINDAYSV2_FORM' and 'action' attribute not found on PAGE2."
            )

        action = str(form["action"])
        page_session_id, session_id, nonce = _form_values(form)
        response = await http.post(
            action,
            headers={"Origin": URL, "Referer": FORM_PAGE},
            data={
                "BINDAYSV2_PAGESESSIONID": page_session_id,
                "BINDAYSV2_SESSIONID": session_id,
                "BINDAYSV2_NONCE": nonce,
                "BINDAYSV2_VARIABLES": "e30=",
                "BINDAYSV2_PAGENAME": "PAGE2",
                "BINDAYSV2_PAGEINSTANCE": "0",
                "BINDAYSV2_PAGE2_FIELD293": "true",
                "BINDAYSV2_PAGE2_UPRN": uprn,
                "BINDAYSV2_FORMACTION_NEXT": "BINDAYSV2_PAGE2_FIELD294",
                "BINDAYSV2_PAGE2_FIELD295": "false",
                "BINDAYSV2_PAGE2_FIELD297": "false",
            },
            timeout=30,
        )
        return _results(response.text)


SCRAPER = EastRenfrewshire()
