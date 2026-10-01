"""Cardiff: the council page embeds a webforms proxy; its page token authorises the waste API."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_BASE = "https://app-cprd-webformsproxy-prd.azurewebsites.net"
_URL_FORM = f"{_BASE}/WASTE_wc"
_URL_COLLECTIONS = f"{_BASE}/api/WasteManagement/api/WasteCollection"
_TOKEN = re.compile(r"verificationToken\s*=\s*'([^']+)'")


class Cardiff(Scraper):
    meta = Meta(
        title="Cardiff Council",
        url="https://www.cardiff.gov.uk/collections",
        lads=("W06000015",),
        cases={
            "Glass": {"uprn": "100100124569"},
            "NoGlass": {"uprn": "100100127440"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {
        "Origin": _BASE,
        "Referer": _URL_FORM,
        "User-Agent": "Mozilla/5.0",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        payload = {
            "systemReference": "web",
            "language": "eng",
            "uprn": address.need("uprn"),
        }
        form = await http.get(_URL_FORM)
        token = _TOKEN.search(form.text)
        if token is None:
            raise UpstreamError("Cardiff's bin form did not contain a verification token")
        response = await http.post(
            _URL_COLLECTIONS,
            headers={"VerificationToken": token.group(1)},
            json=payload,
        )

        collections = response.json()
        entries = []
        for week in collections["collectionWeeks"]:
            for bin_data in week["bins"]:
                entries.append(
                    Collection(
                        date=datetime.fromisoformat(week["date"]).date(),
                        type=bin_data["type"],
                    )
                )
        return entries


SCRAPER = Cardiff()
