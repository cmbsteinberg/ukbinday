"""Rotherham: resolve a property through Imactivate's shared API, then fetch its collections."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
)

_BASE = "https://bins.azurewebsites.net/api"
_LA = "Rotherham"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36"
)


async def _resolve_premise(
    address: Address,
    http: Http,
    postcode: str,
    paon: str,
) -> str:
    r = await http.get(
        f"{_BASE}/getaddress",
        params={"postcode": postcode, "localauthority": _LA},
        timeout=15,
    )
    rows = r.json() or []

    if not paon.strip():
        if not rows:
            raise AddressNotFound(f"No addresses found for postcode {postcode}")
        return str(rows[0].get("PremiseID"))

    candidate = match_address(
        address,
        rows,
        text=lambda row: " ".join(
            str(row.get(key, "")).strip()
            for key in ("Address2", "Address1", "Street")
            if row.get(key) is not None
        ),
    )
    return str(candidate.get("PremiseID"))


class Rotherham(Scraper):
    meta = Meta(
        title="Rotherham",
        url="https://www.rotherham.gov.uk/",
        lads=("E08000018",),
        cases={},
    )
    requires = frozenset()
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        premises = address.get("premisesid")

        if not premises and address.postcode:
            premises = await _resolve_premise(
                address,
                http,
                address.postcode,
                address.house_number or "",
            )

        if not premises:
            uprn = address.uprn
            if uprn and uprn.strip().isdigit():
                premises = uprn.strip()

        if not premises:
            raise InputError(
                "Rotherham requires either an Imactivate `premisesid` or a "
                "`postcode` (plus optionally `paon`) to resolve one."
            )

        try:
            resp = await http.get(
                f"{_BASE}/getcollections",
                params={"premisesid": str(premises), "localauthority": _LA},
                timeout=15,
                check=False,
            )
        except UpstreamError:
            return []

        if resp.status_code != 200:
            return []

        try:
            collections: Any = resp.json() or []
        except ValueError:
            return []

        result: list[Collection] = []
        for item in collections:
            if not isinstance(item, Mapping):
                continue

            bin_type = item.get("BinType") or item.get("bintype") or "Unknown"
            date_str = item.get("CollectionDate") or item.get("collectionDate")
            if not isinstance(bin_type, str) or not isinstance(date_str, str) or not date_str:
                continue

            try:
                day = datetime.strptime(date_str.split("T")[0], "%Y-%m-%d").date()
            except ValueError:
                continue

            result.append(Collection(day, bin_type))

        return result


SCRAPER = Rotherham()
