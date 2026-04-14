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
    return [
        {
            "uprn": item["UPRN"],
            "full_address": _format_address(item),
            "postcode": item.get("postcode", postcode),
        }
        for item in data
    ]
