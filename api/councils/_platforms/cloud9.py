"""Cloud9 citizen-mobile API (`apps.cloud9apps.com/<authority>/citizenmobile/mobileapi`).

Every council on it exposes the same two endpoints:

1. `/wastecollections/<uprn>` returns the collection dates for a UPRN.
2. `/addresses?postcode=...` lists properties (with their UPRN), for councils
   where we may have to find the UPRN from the address text.

The API is fronted by two hostnames serving the same data; if one can't be
reached the other is tried. What differs per council is data, in `Cloud9Config`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Literal

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Platform,
    Response,
    Transport,
    UpstreamError,
    match_address,
)

API_DOMAINS = (
    "https://apps.cloud9apps.com",
    "https://apps.cloud9technologies.com",
)
_API_BASE = "/citizenmobile/mobileapi"
_TIMEOUT = 30

_POSTCODE = re.compile(r"([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})", re.IGNORECASE)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

_ADDRESS_FIELDS = (
    "fullAddress",
    "singleLineAddress",
    "address",
    "addressLine1",
    "addressLine2",
    "addressLine3",
    "town",
    "buildingName",
    "buildingNumber",
    "propertyNumber",
    "street",
    "postcode",
)

type Json = dict[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class Cloud9Config:
    authority: str
    """The council's path segment: "arun", "eastdevon"."""
    lookup: Literal["uprn", "uprn_or_address", "uprn_then_address"] = "uprn"
    """"uprn": the UPRN is required. "uprn_or_address": use the UPRN when given, else search
    the postcode and pick the property from the address text. "uprn_then_address": try the
    UPRN, and search by address if that fails or returns nothing."""
    uprn_width: int | None = None
    """Zero-pad the UPRN to this many digits before asking (East Devon wants 12)."""
    api_domains: tuple[str, ...] = API_DOMAINS


def _postcode_of(text: str | None) -> str | None:
    match = _POSTCODE.search(text or "")
    return f"{match.group(1).upper()} {match.group(2).upper()}" if match else None


def _address_string(item: Json) -> str:
    return " ".join(str(item[key]) for key in _ADDRESS_FIELDS if item.get(key) not in (None, "")).strip()


def _clean_type_name(name: str) -> str:
    cleaned = name.strip()
    if cleaned.lower().endswith("collection"):
        cleaned = cleaned[: -len("collection")].strip()
    if cleaned.lower().endswith("bins"):
        cleaned = cleaned[: -len("bins")].strip()
    elif cleaned.lower().endswith("bin"):
        cleaned = cleaned[: -len("bin")].strip()
    return cleaned or name


def _parse_date_string(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    iso_candidate = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
    try:
        return datetime.fromisoformat(iso_candidate).date()
    except ValueError:
        pass
    if iso_match := _ISO_DATE.search(candidate):
        try:
            return datetime.strptime(iso_match.group(), "%Y-%m-%d").date()
        except ValueError:
            pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None


def _extract_dates(details: Json) -> set[date]:
    values: list[Any] = [details.get(key) for key in ("collectionDate", "nextCollectionDate", "nextCollection")]
    values.extend(details.get("collectionDates") or [])
    values.extend(
        (entry.get("collectionDate") or entry.get("nextCollectionDate") or entry.get("date"))
        if isinstance(entry, dict)
        else entry
        for entry in details.get("futureCollections") or []
    )
    next_collection = details.get("nextCollection")
    if not isinstance(next_collection, dict):
        next_collection = {}
    values.append(
        next_collection.get("collectionDate") or next_collection.get("nextCollectionDate") or next_collection.get("date")
    )
    return {parsed for value in values if (parsed := _parse_date_string(value)) is not None}


def _collection_items(data: Json) -> list[tuple[str, Json]]:
    section = data.get("collections")
    if section:
        return list(section.items())
    items: list[tuple[str, Json]] = []
    for key, value in data.items():
        if not key.lower().endswith("collectiondetails"):
            continue
        if isinstance(value, list):
            items.extend((f"{key}_{idx}", entry) for idx, entry in enumerate(value, start=1) if entry)
        elif value:
            items.append((key, value))
    return items


def _collections(payload: Json) -> list[Collection]:
    data = payload.get("wasteCollectionDates") or payload.get("WasteCollectionDates") or payload
    out: list[Collection] = []
    for key, details in _collection_items(data):
        if not details:
            continue
        raw_label = (
            details.get("containerDescription") or details.get("containerName") or details.get("collectionType") or key
        )
        label = _clean_type_name(str(raw_label))
        out.extend(Collection(day, label) for day in sorted(_extract_dates(details)))
    return out


class Cloud9(Platform[Cloud9Config]):
    # The old client used curl_cffi (Chrome impersonation) and forced HTTP/1.1 because the
    # API's ELB can send HTTP/1.1-only headers on HTTP/2 (nghttp2 error 92). `Http` can't
    # force the version; the default transport worked against the live API.
    transport = Transport.CURL_CFFI
    headers: Mapping[str, str] = MappingProxyType(
        {
            "Authorization": "Basic Y2xvdWQ5OmlkQmNWNGJvcjU=",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-version": "2",
        }
    )

    def __init__(self, meta: Meta, config: Cloud9Config, *, icons: Mapping[str, str] | None = None) -> None:
        super().__init__(meta, config, icons=icons)
        self.requires = frozenset({"uprn"}) if config.lookup == "uprn" else frozenset()

    async def _get_json(self, http: Http, path: str, params: Mapping[str, str] | None = None) -> Json:
        """Try each API hostname; only a transport failure moves on to the next."""
        last_error: UpstreamError | None = None
        for domain in self.config.api_domains:
            url = f"{domain.rstrip('/')}/{self.config.authority}{_API_BASE}{path}"
            try:
                r: Response = await http.get(url, params=params, timeout=_TIMEOUT, check=False)
            except UpstreamError as err:
                last_error = err
                continue
            r.raise_for_status()
            payload = r.json()
            if not isinstance(payload, dict):
                raise UpstreamError(f"Cloud9 {path} returned {type(payload).__name__}, expected an object")
            return payload
        raise last_error or UpstreamError("No Cloud9 API domain configured")

    async def _by_uprn(self, http: Http, uprn: str) -> list[Collection]:
        if self.config.uprn_width:
            uprn = uprn.zfill(self.config.uprn_width)
        return _collections(await self._get_json(http, f"/wastecollections/{uprn}"))

    async def _lookup_addresses(self, http: Http, address: Address, search: str) -> list[Json]:
        line = " ".join(part.strip() for part in (address.house_number, address.street) if part and part.strip())
        seen: set[tuple[str, str]] = set()
        attempts: list[tuple[str, str | None]] = [
            ("postcode", _postcode_of(address.postcode)),
            ("postcode", address.postcode),
            ("address", search),
            ("query", search),
            ("address", line),
            ("query", line),
            ("query", address.street),
        ]
        for param, value in attempts:
            cleaned = (value or "").strip()
            if not cleaned or (param, cleaned.lower()) in seen:
                continue
            seen.add((param, cleaned.lower()))
            found = (await self._get_json(http, "/addresses", {param: cleaned})).get("addresses")
            if found:
                return [item for item in found if isinstance(item, dict)]
        raise InputError("Cloud9 returned no addresses for this postcode or address")

    async def _by_address(self, http: Http, address: Address) -> list[Collection]:
        search = address.label or " ".join(
            part.strip() for part in (address.house_number, address.street, address.postcode) if part and part.strip()
        )
        candidates = await self._lookup_addresses(http, address, search)
        selected = match_address(address, candidates, text=_address_string, uprn=lambda item: item.get("uprn"))
        uprn = selected.get("uprn")
        if not uprn:
            raise InputError("The selected address does not expose a UPRN")
        entries = await self._by_uprn(http, str(uprn))
        if not entries:
            raise InputError("No collection data returned for the selected address")
        return entries

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        lookup = self.config.lookup
        if lookup == "uprn":
            return await self._by_uprn(http, address.need("uprn"))
        if lookup == "uprn_or_address":
            if address.uprn:
                return await self._by_uprn(http, address.uprn)
            if not address.postcode:
                raise InputError("Provide a UPRN or postcode + address")
            return await self._by_address(http, address)
        if address.uprn:
            try:
                entries = await self._by_uprn(http, address.uprn)
            except (UpstreamError, ValueError, KeyError, AttributeError):
                entries = []  # fall back to address matching
            if entries:
                return entries
        return await self._by_address(http, address)
