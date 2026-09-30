from __future__ import annotations

import logging
import re

import httpx

from api.config import ADDRESS_API_COMPANY_ID, ADDRESS_API_URL

logger = logging.getLogger(__name__)

_TIMEOUT = 15
_SESSION_PAGE = "https://www.midsuffolk.gov.uk/check-your-collection-day"
# Liferay.authToken is set on every page render. The old p_auth=([^&"]+) form
# stopped matching reliably: some renders omit p_auth, others quote it with ',
# which the negated class swallowed along with the rest of the script block.
_CSRF_RE = re.compile(
    r"Liferay\.authToken\s*=\s*['\"]([A-Za-z0-9]+)['\"]|p_auth=([A-Za-z0-9]+)"
)


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


def _split_address_line_1(
    line1: str | None, line2: str | None
) -> tuple[str | None, str | None]:
    if not line1:
        return None, _title_case(line2) if line2 else None
    line1 = line1.strip()
    m = _HOUSE_NUM_RE.match(line1)
    if m:
        return m.group(1), _title_case(m.group(2))
    return _title_case(line1), _title_case(line2) if line2 else None


async def _get_session(client: httpx.AsyncClient) -> str:
    resp = await client.get(_SESSION_PAGE)
    resp.raise_for_status()
    match = _CSRF_RE.search(resp.text)
    if not match:
        raise RuntimeError("Could not extract CSRF token from session page")
    return match.group(1) or match.group(2)


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
