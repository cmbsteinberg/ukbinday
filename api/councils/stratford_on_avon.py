"""Stratford-on-Avon: posts a UPRN to the council's collection calendar and reads its table."""

from __future__ import annotations

from datetime import datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    soup,
)

_API_URL = "https://www.stratford.gov.uk/waste-recycling/when-we-collect.cfm/part/calendar"
_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
_DATE_FORMAT = "%A, %d/%m/%Y"
_BINS = ("Food waste", "Recycling", "Refuse", "Garden waste")


class StratfordOnAvon(Scraper):
    meta = Meta(
        title="Stratford District Council",
        url="https://stratford.gov.uk",
        lads=("E07000221",),
        cases={
            "Stratford DC": {"uprn": "100071513500"},
            "Alscot Estate": {"uprn": "10024633309"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(
            _API_URL,
            data={
                "frmAddress1": "",
                "frmAddress2": "",
                "frmAddress3": "",
                "frmAddress4": "",
                "frmPostcode": "",
                "frmUPRN": address.need("uprn"),
            },
        )
        page = soup(r.text)
        table = page.find("table", class_="table")
        if not isinstance(table, Tag) or not isinstance(table.tbody, Tag):
            raise UpstreamError("Stratford's collection page has no calendar table")

        collections: list[Collection] = []
        for row in table.tbody.find_all("tr"):
            day = datetime.strptime(row.find("td").text, _DATE_FORMAT).date()
            for idx, cell in enumerate(row.find_all("td", class_="text-center")):
                if cell.find("img", class_="check-img"):
                    collections.append(Collection(day, _BINS[idx]))
        return collections


SCRAPER = StratfordOnAvon()
