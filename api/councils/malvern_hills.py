"""Malvern Hills: resolve a postcode to a UPRN, then POST it to the bin-round lookup."""

from __future__ import annotations

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
    match_address,
    soup,
)

_UPRN_LOOKUP_URL = "https://swict.malvernhills.gov.uk/sw2AddressLookupWS/jaxrs/PostCode"
_API_URL = "https://swict.malvernhills.gov.uk/mhdcroundlookup/HandleSearchScreen"


async def _resolve_uprn(postcode: str, address: Address, http: Http) -> str:
    response = await http.get(
        _UPRN_LOOKUP_URL,
        params={
            "simple": "T",
            "pcode": postcode,
            "authority": "MHDC",
            "historical": "false",
            "hidedummyuprn": "1",
        },
    )
    results: list[dict[str, Any]] = response.json().get("jArray", [])

    if not results:
        raise AddressNotFound(f"No addresses found for postcode {postcode}")

    if address.house_number:
        try:
            candidate = match_address(
                address,
                results,
                text=lambda entry: str(entry.get("Address_Short", "")),
                uprn=lambda entry: entry.get("UPRN"),
            )
            return str(candidate["UPRN"])
        except AddressNotFound:
            if len(results) != 1:
                raise

    if len(results) == 1:
        return str(results[0]["UPRN"])

    raise AddressNotFound(
        f"Multiple addresses found for {postcode} — provide house_number to disambiguate",
        [str(entry.get("Address_Short", "")) for entry in results],
    )


class MalvernHills(Scraper):
    meta = Meta(
        title="Malvern Hills",
        url="https://www.malvernhills.gov.uk/",
        lads=("E07000235",),
        cases={},
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.uprn
        if not uprn:
            if not address.postcode:
                raise InputError("Malvern Hills needs a UPRN or a postcode")
            uprn = await _resolve_uprn(address.postcode, address, http)

        response = await http.post(
            _API_URL,
            data={"nmalAddrtxt": "", "alAddrsel": uprn},
        )

        page = soup(response.text)
        table = page.find("table")
        if not table:
            raise AddressNotFound(
                "No results table found — UPRN may be invalid or address not in bin round records"
            )

        table_body = table.find("tbody")
        rows = table_body.find_all("tr")

        collections: list[Collection] = []
        for row in rows:
            columns = [cell.text.strip() for cell in row.find_all("td")]
            values = [value for value in columns if value]
            try:
                if "Not applicable" in values[1]:
                    continue
                bin_type = values[0].replace("collection", "").strip()
                day = datetime.strptime(values[1], "%A %d/%m/%Y").date()
            except (IndexError, ValueError):
                continue
            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = MalvernHills()
