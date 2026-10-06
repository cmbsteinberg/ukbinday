"""Kirklees: an AchieveForms lookup validates the UPRN against the postcode, then fetches collection dates."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
)
from api.councils._platforms.achieveforms import init_session, rows, run_lookup

_HOSTNAME = "my.kirklees.gov.uk"
_BASE_URL = f"https://{_HOSTNAME}"
_API_URL = f"{_BASE_URL}/apibroker/runLookup"
_SERVICE_PATH = "/service/Bins_and_recycling___Manage_your_bins"
_FORM_ID = "AF-Form-0d9c96d0-4067-4bea-9a5b-06f32a675be6"

_LOOKUP_ADDRESS = "58049013ca4c9"
_LOOKUP_PROP_TYPE = "659c2c2386104"
_LOOKUP_UPRN_VALID = "631615c4bd3b7"
_LOOKUP_COLLECTIONS = "65e08e60b299d"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{_BASE_URL}{_SERVICE_PATH}",
}


async def _lookup(
    http: Http, sid: str, lookup_id: str, form_values: dict[str, Any]
) -> dict[str, Any]:
    return await run_lookup(
        http, _API_URL, sid, lookup_id, form_values, body={"formId": _FORM_ID}
    )


def _rows(reply: dict[str, Any]) -> dict[str, Any]:
    """rows_data keyed by row (a list answer is keyed by each row's `name`)."""
    return rows(reply, key="name")


class Kirklees(Scraper):
    meta = Meta(
        title="Kirklees Council",
        url="https://www.kirklees.gov.uk",
        lads=("E08000034",),
        cases={
            "Midgebottom House": {"uprn": "83074265", "postcode": "HD9 7HA"},
            "HD8 8NA test": {"uprn": "83194785", "postcode": "HD8 8NA"},
        },
    )
    requires = frozenset({"uprn", "postcode"})
    headers = _HEADERS
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        postcode = address.need("postcode")

        sid = await init_session(
            http,
            None,
            f"{_BASE_URL}/authapi/isauthenticated",
            _HOSTNAME,
            uri=f"{_BASE_URL}{_SERVICE_PATH}",
            domain_url=f"{_BASE_URL}/apibroker/domain/{_HOSTNAME}",
        )

        address_data = await _lookup(
            http, sid, _LOOKUP_ADDRESS, {"Section 1": {"Postcode": {"value": postcode}}}
        )
        address_rows = _rows(address_data)
        if uprn not in address_rows:
            raise AddressNotFound(
                f"No property matching UPRN {uprn} at postcode {postcode}",
                list(address_rows.keys()),
            )

        selected = address_rows[uprn]
        property_reference = selected.get("PropertyReference", "")
        house = selected.get("Premise", "")
        street = selected.get("Street", "")
        town = selected.get("Town", "")
        full_address = selected.get("display", "")
        postcode_length = str(len(postcode))

        search_section: dict[str, Any] = {
            "PowerSuite_Available": {"value": "True"},
            "PowerSuite_Available1": {"value": "True"},
            "productName": {"value": "Self"},
            "uprn2": {"value": uprn},
            "validatedUPRN": {"value": uprn},
            "suppliedUPRN": {"value": uprn},
            "uprnFinal": {"value": uprn},
            "validPropertyFlag": {"value": "yes"},
            "sSection": {"value": "1"},
            "flatOrSubBuildingFinal": {"value": ""},
            "houseFinal": {"value": house},
            "streetFinal": {"value": street},
            "townFinal": {"value": town},
            "postcodeFinal": {"value": postcode},
            "fullAddressFinal": {"value": full_address},
            "customerAddress": {
                "value": {
                    "Section 1": {
                        "searchForAddress": {"value": "yes"},
                        "Postcode": {"value": postcode},
                        "List": {"value": uprn},
                        "House": {"value": house},
                        "Street": {"value": street},
                        "Town": {"value": town},
                        "UPRN": {"value": uprn},
                        "PropertyReference": {"value": property_reference},
                        "postcode": {"value": ""},
                        "house": {"value": ""},
                        "flat": {"value": ""},
                        "street": {"value": ""},
                        "town": {"value": ""},
                        "fullAddress": {"value": full_address},
                        "lengthPostCode": {"value": postcode_length},
                    }
                }
            },
        }

        property_data = await _lookup(http, sid, _LOOKUP_PROP_TYPE, {"Search": search_section})
        property_rows = _rows(property_data)
        gov_category = ""
        property_type = "Residential"
        if property_rows:
            first = next(iter(property_rows.values()))
            gov_category = first.get("GovDeliveryCategorye", "")
            property_type = first.get("PropertyType", "Residential") or "Residential"

        search_section["binsPropertyType"] = {
            "value": {
                "Section 1": {
                    "PropertyType": {"value": property_type},
                    "GovDeliveryCategorye": {"value": gov_category},
                }
            }
        }
        search_section["GovDeliveryCategorye"] = {"value": gov_category}
        search_section["PropertyType"] = {"value": property_type}

        await _lookup(http, sid, _LOOKUP_UPRN_VALID, {"Search": search_section})

        today = date.today()
        from_date = (today - timedelta(days=7)).strftime("%d/%m/%Y")
        to_date = (today + timedelta(days=28)).strftime("%d/%m/%Y")

        collection_data = await _lookup(
            http,
            sid,
            _LOOKUP_COLLECTIONS,
            {
                "Search": search_section,
                "Your bins": {
                    "GovDeliveryCategorye": {"value": gov_category},
                    "NextCollectionFromDate": {"value": from_date},
                    "NextCollectionToDate": {"value": to_date},
                },
            },
        )
        collection_rows = _rows(collection_data)

        if not collection_rows:
            raise UpstreamError(f"Kirklees: no collection data returned for UPRN {uprn}.")

        collections: list[Collection] = []
        for row in collection_rows.values():
            date_text = row.get("NextCollectionDate", "")
            bin_type = row.get("label", "") or row.get("ServiceItemName", "")
            if not date_text or not bin_type:
                continue
            try:
                collection_date = datetime.fromisoformat(date_text).date()
            except ValueError:
                continue
            collections.append(Collection(date=collection_date, type=str(bin_type)))

        return collections


SCRAPER = Kirklees()
