"""Isle of Anglesey: authenticate with AchieveForms, resolve by postcode if needed, then fetch the UPRN schedule."""

from __future__ import annotations

from datetime import UTC, datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    match_address,
    parse_date,
)
from api.councils._platforms.achieveforms import init_session, rows, run_lookup

_HOSTNAME = "myaccount.anglesey.gov.wales"
_BASE_URL = f"https://{_HOSTNAME}"
_AUTH_URL = f"{_BASE_URL}/authapi/isauthenticated"
_LOOKUP_URL = f"{_BASE_URL}/apibroker/runLookup"
_TIMEOUT = 60

_ADDRESS_LOOKUP_ID = "61c43f6dabddb"
_SCHEDULE_LOOKUP_ID = "6362261cd6bd9"


async def _get_uprn_from_postcode_and_paon(
    http: Http, sid: str, postcode: str, paon: str
) -> str:
    addresses = rows(
        await run_lookup(
            http,
            _LOOKUP_URL,
            sid,
            _ADDRESS_LOOKUP_ID,
            {"Section 1": {"postcode_search": {"value": postcode}}},
            timeout=_TIMEOUT,
        )
    )
    if not addresses:
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
        postcode = address.postcode
        paon = address.house_number
        if user_uprn is None and postcode is None:
            raise InputError("Either 'uprn' or 'postcode' is required")
        if user_uprn is None and paon is None:
            raise InputError("A house number or name is required with postcode")

        sid = await init_session(
            http, None, _AUTH_URL, _HOSTNAME, uri=_BASE_URL, timeout=_TIMEOUT
        )
        if user_uprn is None:
            user_uprn = await _get_uprn_from_postcode_and_paon(
                http, sid, str(postcode), str(paon)
            )

        schedule = rows(
            await run_lookup(
                http,
                _LOOKUP_URL,
                sid,
                _SCHEDULE_LOOKUP_ID,
                {
                    "Section 1": {
                        "calcUPRN": {"value": user_uprn},
                        "calcDate": {"value": datetime.now(UTC).strftime("%d/%m/%Y")},
                        "calcLang": {"value": "en"},
                    }
                },
                timeout=_TIMEOUT,
            )
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
