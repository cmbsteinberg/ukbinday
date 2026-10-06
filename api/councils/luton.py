"""Luton: an AchieveForms lookup keyed on the UPRN, returning an HTML table of collections."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    soup,
)
from api.councils._platforms.achieveforms import init_session, rows, run_lookup

_HOSTNAME = "myforms.luton.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_FORM_URI = f"https://{_HOSTNAME}/service/Find_my_bin_collection_date"
_API_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://{_HOSTNAME}/fillform/?iframe_id=fillform-frame-1&db_id=",
}


class Luton(Scraper):
    meta = Meta(
        title="Luton",
        url="https://myforms.luton.gov.uk",
        lads=("E06000032",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI)

        reply_rows = rows(
            await run_lookup(
                http,
                _API_URL,
                sid,
                "65cb710f8d525",
                {"Find my bin collection date": {"id": {"value": f"1-{uprn}"}}},
                no_retry="true",
                headers=_HEADERS,
            )
        )
        rows_data = reply_rows.get(uprn)
        if rows_data is None:
            raise AddressNotFound(f"Luton has no collection data for UPRN {uprn}")

        collections = []
        for row in soup(rows_data["html"]).find_all("tr"):
            cells = row.find_all("td")
            bin_type = cells[1].text
            if not bin_type or not cells[0].text:
                continue
            try:
                collection_date = datetime.strptime(cells[0].text, "%A %d %b %Y").date()
            except ValueError:
                continue
            collections.append(Collection(collection_date, bin_type))
        return collections


SCRAPER = Luton()
