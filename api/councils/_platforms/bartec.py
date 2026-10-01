"""Bartec Collective "public dashboard" portals (High Peak, Scottish Borders...).

Every portal is the same ASP.NET Razor page:

1. `GET <url>` for the `__RequestVerificationToken` form field.
2. `POST <url>?handler=SelectPrem` with the token, postcode and UPRN. The page
   embeds Syncfusion data sources as `dataSource": ejs.data.DataUtil.parse.isJson([...])`:
   one lists the postcode's premises (rows with `UPRN`), one the property's
   appointments (rows with `Subject` and `StartTime`).

What differs per council is the page URL, in `BartecConfig`.

Other councils that run Bartec behind their own API or form (Bath, Bedford,
Blackpool, Durham, Enfield, the AchieveForms councils...) share nothing at the
HTTP level and stay bespoke.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Platform,
    UpstreamError,
    soup,
)

_TIMEOUT = 30
_DATA_SOURCE = re.compile(r'dataSource"\s*:\s*ejs\.data\.DataUtil\.parse\.isJson\(\s*')


@dataclass(frozen=True, slots=True, kw_only=True)
class BartecConfig:
    url: str
    """The dashboard page: "https://bins.highpeak.gov.uk/PublicDashboard"."""


def _data_sources(html: str) -> list[list[dict[str, Any]]]:
    """Every embedded data source that is a list of objects."""
    decoder = json.JSONDecoder()
    sources: list[list[dict[str, Any]]] = []
    for match in _DATA_SOURCE.finditer(html):
        try:
            data, _ = decoder.raw_decode(html, match.end())
        except ValueError:
            continue
        if isinstance(data, list):
            sources.append([item for item in data if isinstance(item, dict)])
    return sources


def _block_with(sources: list[list[dict[str, Any]]], key: str) -> list[dict[str, Any]]:
    return next((block for block in sources if block and key in block[0]), [])


def _uprn(value: object) -> str:
    """The dashboard serialises UPRNs as floats: 10010724037.0."""
    return str(int(value)) if isinstance(value, int | float) else str(value)


class Bartec(Platform[BartecConfig]):
    requires = frozenset({"postcode", "uprn"})
    headers: Mapping[str, str] = MappingProxyType(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
    )

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        url = self.config.url
        postcode = address.need("postcode")
        uprn = address.need("uprn")

        r = await http.get(url, timeout=_TIMEOUT)
        token = soup(r.text).find("input", {"name": "__RequestVerificationToken"})
        value = token.get("value") if token is not None else None
        if not value:
            raise UpstreamError(f"No verification token on {url}")

        parts = urlsplit(url)
        r = await http.post(
            url,
            params={"handler": "SelectPrem"},
            data={
                "__RequestVerificationToken": str(value),
                "SelectedPostcode": postcode,
                "SelectedPremises": uprn,
            },
            headers={"Referer": url, "Origin": f"{parts.scheme}://{parts.netloc}"},
            timeout=_TIMEOUT,
        )

        sources = _data_sources(r.text)
        appointments = _block_with(sources, "Subject")
        if not appointments:
            suggestions = [
                f"{p['Premises']} (UPRN {_uprn(p['UPRN'])})"
                for p in _block_with(sources, "UPRN")
                if p.get("Premises") and p.get("UPRN") is not None
            ]
            raise AddressNotFound(f"No collections for UPRN {uprn} in {postcode}", suggestions)

        collections: list[Collection] = []
        for item in appointments:
            subject = item.get("Subject")
            start = item.get("StartTime")
            if not isinstance(subject, str) or not subject or not isinstance(start, str):
                continue
            try:
                day = datetime.fromisoformat(start).date()
            except ValueError:
                continue
            collections.append(Collection(day, subject))
        return collections
