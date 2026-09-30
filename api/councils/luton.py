"""Luton: an AchieveForms lookup keyed on the UPRN, returning an HTML table of collections."""

from __future__ import annotations

import time
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, soup

_SESSION_URL = (
    "https://myforms.luton.gov.uk/authapi/isauthenticated"
    "?uri=https%253A%252F%252Fmyforms.luton.gov.uk%252Fservice%252FFind_my_bin_collection_date"
    "&hostname=myforms.luton.gov.uk&withCredentials=true"
)
_API_URL = "https://myforms.luton.gov.uk/apibroker/runLookup"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://myforms.luton.gov.uk/fillform/?iframe_id=fillform-frame-1&db_id=",
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

        session_response = await http.get(_SESSION_URL)
        sid = session_response.json()["auth-session"]

        params = {
            "id": "65cb710f8d525",
            "repeat_against": "",
            "noRetry": "true",
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "_": str(int(time.time() * 1000)),
            "sid": sid,
        }
        payload = {
            "formValues": {
                "Find my bin collection date": {
                    "id": {"value": f"1-{uprn}"},
                },
            }
        }
        response = await http.post(_API_URL, json=payload, headers=_HEADERS, params=params)
        rows_data = response.json()["integration"]["transformed"]["rows_data"][uprn]

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
