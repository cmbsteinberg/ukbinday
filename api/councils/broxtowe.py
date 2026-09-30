"""Broxtowe: Firmstep form. Look the postcode up, pick the property, submit, read the `bartec` table.

Each table row is a bin followed by its dates (the first two cells are labels).
"""

from __future__ import annotations

from datetime import datetime

from bs4 import Tag

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
    match_address,
    soup,
)
from api.councils._platforms.firmstep import TIMEOUT, hidden_inputs, lookup_addresses

_HOST = "https://selfservice.broxtowe.gov.uk"
_FORM = f"{_HOST}/renderform?t=217&k=9D2EF214E144EE796430597FB475C3892C43C528"


class Broxtowe(Scraper):
    meta = Meta(
        title="Broxtowe Borough Council",
        url="https://www.broxtowe.gov.uk/",
        lads=("E07000172",),
        cases={
            "100031343805 NG9 2NL": {"uprn": "100031343805", "postcode": "NG9 2NL"},
            "100031308988 NG9 4DU": {"uprn": "100031308988", "postcode": "NG9 4DU"},
        },
    )
    requires = frozenset({"postcode"})
    transport = Transport.CURL_CFFI
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        form_inputs = await hidden_inputs(http, _FORM)
        addresses = await lookup_addresses(http, f"{_HOST}/core/addresslookup", postcode)
        # Keys are "U" + UPRN.
        key, label = match_address(
            address,
            addresses.items(),
            text=lambda item: item[1],
            uprn=lambda item: item[0].strip().upper().removeprefix("U"),
        )

        r = await http.post(
            f"{_HOST}/RenderForm",
            data={
                **form_inputs,
                "Trigger": "submit",
                "TriggerCtl": "",
                "FF5683": key,
                "FF5683lbltxt": label,
                "FF5683-text": postcode,
            },
            timeout=TIMEOUT,
        )
        table = soup(r.text).find("table", class_="bartec")
        rows = table.find_all("tr") if isinstance(table, Tag) else []
        if len(rows) < 2:
            raise UpstreamError("could not get valid data from broxtowe.gov.uk")

        collections = []
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            bin_type = cells[0].text
            for cell in cells[2:]:
                if cell.text == "":
                    continue
                try:
                    day = datetime.strptime(cell.text, "%A, %d %B %Y").date()
                except ValueError:
                    continue
                collections.append(Collection(day, bin_type))
        return collections


SCRAPER = Broxtowe()
