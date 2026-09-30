"""Isle of Anglesey: authenticate with AchieveForms, resolve by postcode if needed, then fetch the UPRN schedule."""

from __future__ import annotations

from datetime import UTC, datetime
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
    parse_date,
)

_BASE_URL = "https://myaccount.anglesey.gov.wales"
_SESSION_URL = (
    f"{_BASE_URL}/authapi/isauthenticated"
    "?uri=https%3A%2F%2Fmyaccount.anglesey.gov.wales"
    "&hostname=myaccount.anglesey.gov.wales&withCredentials=true"
)
_LOOKUP_URL = f"{_BASE_URL}/apibroker/runLookup"

_ADDRESS_LOOKUP_ID = "61c43f6dabddb"
_SCHEDULE_LOOKUP_ID = "6362261cd6bd9"


async def _initialise_session(http: Http) -> None:
    response = await http.get(_SESSION_URL, timeout=60)
    try:
        if not response.json().get("auth-session"):
            raise UpstreamError("Failed to obtain an Isle of Anglesey session")
    except ValueError as exc:
        raise UpstreamError("Failed to decode Isle of Anglesey session response") from exc


async def _run_lookup(http: Http, lookup_id: str, payload: dict[str, Any]) -> Any:
    response = await http.post(
        _LOOKUP_URL,
        params={"id": lookup_id},
        json=payload,
        timeout=60,
    )
    try:
        return response.json()["integration"]["transformed"]["rows_data"]
    except ValueError as exc:
        raise UpstreamError("Failed to decode Isle of Anglesey lookup response") from exc
    except KeyError as exc:
        raise UpstreamError("Unexpected Isle of Anglesey lookup response structure") from exc


async def _get_uprn_from_postcode_and_paon(
    http: Http, postcode: str, paon: str
) -> str:
    addresses = await _run_lookup(
        http,
        _ADDRESS_LOOKUP_ID,
        {"formValues": {"Section 1": {"postcode_search": {"value": postcode}}}},
    )
    if not isinstance(addresses, dict) or not addresses:
        raise AddressNotFound(f"No addresses found for postcode {postcode}")

    candidates = [
        (uprn, address_data)
        for uprn, address_data in addresses.items()
        if isinstance(address_data, dict)
    ]
    selected = match_address(
        Address(postcode=postcode, house_number=paon),
        candidates,
        text=lambda candidate: " ".join(
            str(candidate[1].get(field, ""))
            for field in ("display", "house", "flatHouse")
        ),
        uprn=lambda candidate: candidate[0],
    )
    return str(selected[0])


class IsleOfAnglesey(Scraper):
    meta = Meta(
        title="Isle of Anglesey",
        url="https://www.anglesey.gov.wales/en/Residents/Bins-and-recycling/Waste-Collection-Day.aspx",
        lads=("W06000001",),
        cases={},
    )
    requires = frozenset()

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        user_uprn = address.uprn
        if user_uprn is None:
            if address.postcode is None:
                raise InputError("Either 'uprn' or 'postcode' is required")
            paon = address.house_number
            if paon is None:
                raise InputError("A house number or name is required with postcode")
            user_uprn = await _get_uprn_from_postcode_and_paon(
                http, address.postcode, paon
            )

        await _initialise_session(http)
        schedule = await _run_lookup(
            http,
            _SCHEDULE_LOOKUP_ID,
            {
                "formValues": {
                    "Section 1": {
                        "calcUPRN": {"value": user_uprn},
                        "calcDate": {
                            "value": datetime.now(UTC).strftime("%d/%m/%Y")
                        },
                        "calcLang": {"value": "en"},
                    }
                }
            },
        )
        if not schedule:
            raise AddressNotFound("No collection data found")

        collections: list[Collection] = []
        for row in schedule.values():
            try:
                service = row["Service"]
                date_text = row["Date"]
                if not isinstance(service, str) or not isinstance(date_text, str):
                    continue
                collections.append(Collection(parse_date(date_text), service))
            except (KeyError, ValueError):
                continue
        return collections


SCRAPER = IsleOfAnglesey()
