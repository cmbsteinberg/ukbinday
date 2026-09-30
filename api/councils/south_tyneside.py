"""South Tyneside: look up properties by postcode, then retrieve their collection dates."""

from __future__ import annotations

import json
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, match_address

_TITLE = "South Tyneside Council"
_URL = "https://southtyneside.gov.uk"
_API = "https://www.southtyneside.gov.uk/apiserver/ajaxlibrary"
_HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": "https://www.southtyneside.gov.uk/article/1023/Bin-collection-dates",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/112.0",
}


class SouthTyneside(Scraper):
    meta = Meta(
        title=_TITLE,
        url=_URL,
        lads=("E08000023",),
        cases={
            "Test_001": {"postcode": "NE34 8RY", "uprn": "100000342955"},
            "Test_002": {"postcode": "SR6 7AJ", "uprn": "100000359535"},
            "Test_003": {"postcode": "NE31 1LY", "uprn": "100000304486"},
        },
    )
    requires = frozenset({"postcode"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").replace(" ", "")
        payload = json.dumps(
            {
                "id": "1682761045902",
                "jsonrpc": "2.0",
                "method": "stc.common.snippets.getAddressList",
                "params": {"localonly": "true", "postcode": postcode},
            }
        )
        r1 = await http.post(_API, content=payload)
        addresses = r1.json()["result"]["ReturnedList"]
        item = match_address(
            address,
            addresses,
            text=lambda candidate: candidate["Address"],
            uprn=lambda candidate: candidate["UPRN"].lstrip("S"),
        )

        payload = json.dumps(
            {
                "id": "1682761056660",
                "jsonrpc": "2.0",
                "method": "stc.waste.collections.getDates",
                "params": {"addresscode": f"{item['UPRN']}|{item['Address']}"},
            }
        )
        r2 = await http.post(_API, content=payload)
        collections = r2.json()["result"]["SortedCollections"]

        entries = []
        for collection in collections:
            for monthyear in collection["Collections"]:
                entries.append(
                    Collection(
                        date=datetime.strptime(
                            monthyear["DateofCollection"], "%Y-%m-%dT%H:%M:%S"
                        ).date(),
                        type=monthyear["TypeClass"],
                    )
                )

        return entries


SCRAPER = SouthTyneside()
