from __future__ import annotations

import logging
import re

import httpx

from api.config import ADDRESS_API_COMPANY_ID, ADDRESS_API_URL

logger = logging.getLogger(__name__)

_TIMEOUT = 15
_SESSION_PAGE = "https://www.midsuffolk.gov.uk/check-your-collection-day"
_CSRF_RE = re.compile(r"p_auth=([^&\"]+)")


def _title_case(s: str) -> str:
    return re.sub(r"\b\w", lambda m: m.group().upper(), s.lower())


def _format_address(item: dict) -> str:
    parts = [
        item.get("addressLine1"),
        item.get("addressLine2"),
        item.get("addressLine3"),
        item.get("addressLine4"),
        item.get("city"),
    ]
    formatted = [_title_case(p) for p in parts if p]
    formatted.append(item.get("postcode", ""))
    return ", ".join(formatted)


_HOUSE_NUM_RE = re.compile(r"^([0-9]+[A-Za-z]?)\s+(.*)$")

# Leading building number in line 2 ("18" in "18 Aylsham Road").
_BUILDING_NUM_RE = re.compile(r"^([0-9]+[A-Za-z]?)\s+")

# Sub-building (flat/room) prefixes. Keyword set follows the sub_building
# taxonomy in moj-analytical-services/uk_address_matcher (MIT): a dwelling
# keyword plus a flat/room identifier ("Flat 55", "Flat A",
# "Ground Floor Flat 2", "Room 5"). Either a floor descriptor or an
# identifier must be present, so bare names ("Flat Fish", a chip shop)
# fall through untouched. The trailing building name is dropped: council
# search portals match on the sub-building + street, and the extra building
# text yields zero results (e.g. Mid Sussex Whitespace portal).
_SUB_BUILDING_RE = re.compile(
    r"^("
    r"((?:Basement|Ground|First|Second|Third|Fourth|Lower\s+Ground|Upper)(?:\s+Floor)?\s+)?"
    r"(Flat|Apartment|Apartments|Maisonette|Unit|Room"
    r"|Studio\s+Flat|Studio\s+Apartment|Garden\s+Flat|Penthouse|Duplex|Annexe?)"
    r"((?:\s+[0-9]+[A-Za-z]?)|(?:\s+[A-Z]))?"
    r")\b[,\s]*(.*)$",
    re.IGNORECASE,
)

# Street suffixes, used to tell "55 Harlands House" (building name in line 1,
# real street in line 2) apart from "23 High Street" (street already in
# line 1, line 2 is a locality). Heuristic only — see _split_address_line_1.
_STREET_SUFFIX_RE = re.compile(
    r"\b(Road|Street|Avenue|Lane|Close|Drive|Way|Crescent|Terrace|"
    r"Gardens|Grove|Place|Court|Square|Hill|Rise|Walk|Approach|"
    r"Parade|Broadway|Gate|Mead|Quay|View|Green|Park)\b",
    re.IGNORECASE,
)


def _split_address_line_1(
    line1: str | None, line2: str | None
) -> tuple[str | None, str | None]:
    if not line1:
        return None, _title_case(line2) if line2 else None
    line1 = line1.strip()
    m = _SUB_BUILDING_RE.match(line1)
    if m and (m.group(2) is not None or m.group(4) is not None):
        sub = re.sub(r"\s+", " ", m.group(1)).strip()
        remainder = m.group(5).strip(" ,")
        if line2:
            street = line2
            if not remainder:
                # Bare sub-unit of a numbered building ("Room 5" in
                # "18 Aylsham Road"): portals list building-first
                # ("18, ROOM 5, ..."), so lead with the building number.
                bm = _BUILDING_NUM_RE.match(line2.strip())
                if bm and not sub.upper().startswith(bm.group(1).upper() + " "):
                    sub = f"{bm.group(1)} {sub}"
            return _title_case(sub), _title_case(street)
        return _title_case(sub), _title_case(remainder) if remainder else None
    m = _HOUSE_NUM_RE.match(line1)
    if m:
        number, rest = m.group(1), m.group(2)
        if (
            line2
            and not _STREET_SUFFIX_RE.search(rest)
            and _STREET_SUFFIX_RE.search(line2)
        ):
            # "55 Harlands House" + line2 "Harlands Road": rest is a
            # building name, line2 is the real street.
            return number, _title_case(line2)
        return number, _title_case(rest)
    return _title_case(line1), _title_case(line2) if line2 else None


async def _get_session(client: httpx.AsyncClient) -> str:
    resp = await client.get(_SESSION_PAGE)
    resp.raise_for_status()
    match = _CSRF_RE.search(resp.text)
    if not match:
        raise RuntimeError("Could not extract CSRF token from session page")
    return match.group(1)


async def search_addresses(postcode: str) -> list[dict]:
    postcode = postcode.strip().upper()

    body = (
        '{"/placecube_digitalplace.addresscontext/search-address-by-postcode":'
        f'{{"companyId":"{ADDRESS_API_COMPANY_ID}","postcode":"{postcode}","fallbackToNationalLookup":false}}}}'
    )

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        csrf_token = await _get_session(client)

        resp = await client.post(
            ADDRESS_API_URL,
            content=body,
            headers={
                "accept": "*/*",
                "content-type": "text/plain;charset=UTF-8",
                "x-csrf-token": csrf_token,
                "referer": _SESSION_PAGE,
            },
        )
        resp.raise_for_status()

    data = resp.json()
    results = []
    for item in data:
        line1 = item.get("addressLine1")
        line2 = item.get("addressLine2")
        house, street = _split_address_line_1(line1, line2)
        results.append(
            {
                "uprn": item["UPRN"],
                "full_address": _format_address(item),
                "postcode": item.get("postcode", postcode),
                "address_line_1": _title_case(line1) if line1 else None,
                "house_number_or_name": house,
                "street": street,
            }
        )
    return results
