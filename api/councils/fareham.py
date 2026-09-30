"""Fareham: searches the domestic bin-collections API by postcode, then matches address rows."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date

from dateutil.parser import parse as date_parse

from api.councils._base import Address, AddressNotFound, Collection, Http, Meta, Scraper

_API_URL = "https://www.fareham.gov.uk/internetlookups/search_data.aspx"
_API_LIST = "DomesticBinCollections2025on"


def _fix_json(text: str) -> str:
    rows_start = text.find('"rows": [')
    if rows_start == -1:
        return text
    prefix = text[:rows_start]
    rows_section = text[rows_start:]
    rows_section = re.sub(r'\{\s*"Row":\s*"\d+",\s*(?=\{)', "", rows_section)
    rows_section = re.sub(r"(},)(\s*)(\")", r"\1\2{\3", rows_section)
    return prefix + rows_section


async def _request_rows(http: Http, postcode: str) -> list[dict[str, object]]:
    response = await http.get(
        _API_URL,
        params={
            "type": "JSON",
            "list": _API_LIST,
            "Road or Postcode": postcode,
        },
        headers={"user-agent": "Mozilla/5.0"},
        timeout=30,
    )
    payload = json.loads(_fix_json(response.text))
    return payload.get("data", {}).get("rows", [])


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _tokenize(value: str) -> list[str]:
    if not value:
        return []
    return re.findall(r"[a-z0-9]+", value.lower())


def _split_house_number(value: str) -> tuple[str | None, str]:
    match = re.match(r"\s*(\d+[a-zA-Z]?)\s+(.+)", value)
    if match:
        return match.group(1), match.group(2).strip()
    return None, value.strip()


def _filter_rows(
    rows: Iterable[dict[str, object]], postcode: str, street: str
) -> list[dict[str, object]]:
    postcode_norm = _normalize(postcode)
    house_number, street_name = _split_house_number(street)
    street_tokens = set(_tokenize(street_name))
    matches = []

    for row in rows:
        address = row.get("Address", "")
        if not isinstance(address, str):
            address = ""
        address_norm = _normalize(address)
        address_tokens = set(_tokenize(address))

        if postcode_norm and postcode_norm not in address_norm:
            continue
        if street_tokens and not street_tokens.issubset(address_tokens):
            continue
        if house_number and house_number.lower() not in address_tokens:
            continue

        matches.append(row)

    return matches


def _extract_collections(value: str) -> list[Collection]:
    collections = []
    if not value:
        return collections
    pattern = r"(?P<date>\d{1,2}\/\d{1,2}\/\d{4}|today) \((?P<waste_type>[^)]+)\)"
    for match in re.finditer(pattern, value):
        if match.group("date") == "today":
            collection_date = date.today()
        else:
            collection_date = date_parse(match.group("date"), dayfirst=True).date()
        collections.append(Collection(collection_date, match.group("waste_type")))
    return collections


def _extract_garden_collection(value: str) -> list[Collection]:
    collections = []
    if not value:
        return collections
    match = re.search(r"(?P<date>\d{1,2}\/\d{1,2}\/\d{4})", value)
    if match:
        collection_date = date_parse(match.group("date"), dayfirst=True).date()
        collections.append(Collection(collection_date, "Garden Waste"))
    return collections


class Fareham(Scraper):
    meta = Meta(
        title="Fareham Borough Council",
        url="https://www.fareham.gov.uk",
        lads=("E07000087",),
        cases={
            "HUNTS_POND_ROAD": {"street": "Hunts pond road", "postcode": "PO14 4PL"},
            "CHRUCH_ROAD": {"street": "Church road", "postcode": "SO31 6LW"},
            "SEGENSWORTH_ROAD": {
                "house_number": "203",
                "street": "Segensworth road",
                "postcode": "PO15 5EL",
            },
        },
    )
    requires = frozenset({"postcode", "street"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        street = address.need("street")
        if address.house_number:
            street = f"{address.house_number} {street}"

        rows = await _request_rows(http, postcode)
        if not rows:
            raise AddressNotFound(
                f"Fareham has no bin collection information for postcode {postcode}"
            )

        matches = _filter_rows(rows, postcode, street)
        if not matches:
            raise AddressNotFound(
                f"No Fareham bin collection address matches {street!r} in {postcode}"
            )

        collections = []
        for row in matches:
            bin_info = row.get("BinCollectionInformation", "")
            if isinstance(bin_info, str):
                collections.extend(_extract_collections(bin_info))

            garden_info = row.get("GardenWasteBinDay<br/>(seenotesabove)")
            if isinstance(garden_info, str) and garden_info:
                collections.extend(_extract_garden_collection(garden_info))

        return collections


SCRAPER = Fareham()
