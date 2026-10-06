"""Ceredigion: submit a postcode to the council's form, select an address, and read its collection results."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    parse_date,
    soup,
    text_of,
)

FORM_URL = "https://forms.ceredigion.gov.uk/ebase/ufsmain?formid=REFUSE_ROUTES"
AJAX_URL = "https://forms.ceredigion.gov.uk/ebase/ufsajax"
_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


def _find_ctrl(html: str, label: str) -> str | None:
    for tag in re.findall(r"<input[^>]*>", html):
        if f'data-ebv-desc="{label}"' in tag:
            match = re.search(r'id="CTID-(\w+)-', tag)
            if match:
                return match.group(1)
    return None


def _find_ctrl_button(html: str, label: str) -> str | None:
    match = re.search(
        rf'CTID-(\w+)-_[^>]*eb-\w+-Button[^>]*value=["\']({re.escape(label)})["\']',
        html,
    )
    return match.group(1) if match else None


def _find_ctrl_button_in_html(html_parts: str, label: str) -> str | None:
    match = re.search(
        rf'CTID-(\w+)-_[^>]*eb-\w+-Button[^>]*value=["\']({re.escape(label)})["\']',
        html_parts,
    )
    return match.group(1) if match else None


def _find_select_ctrl(html: str) -> str | None:
    match = re.search(r'<select[^>]*class="[^"]*?CTID-(\w+)-', html)
    return match.group(1) if match else None


def _extract_html(resp_json: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for ctrl in resp_json.get("updatedControls", []):
        if not isinstance(ctrl, Mapping):
            continue
        html = ctrl.get("html", "")
        if html:
            parts.append(str(html))
    return "\n".join(parts)


def _address_options(html: str) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    for option in soup(html).select("option[value]"):
        value = option.get("value")
        if isinstance(value, str) and value.isdigit():
            options.append((value, text_of(option)))
    return options


def _parse_results(html: str) -> list[Collection]:
    collections: list[Collection] = []

    blocks = re.split(r"(?=Next collection:)", html)
    for block in blocks[1:]:
        date_match = re.search(
            r"Next collection:</strong>\s*(\w+day)\s+(\d+)(?:st|nd|rd|th)?\s+(\w+)",
            block,
        )
        if not date_match:
            continue

        _, day, month = date_match.groups()
        try:
            collection_date = parse_date(f"{day} {month}")
        except ValueError:
            continue

        bin_types = re.findall(r'aria-label="([^"]+)"', block)
        bin_types = [bin_type for bin_type in bin_types if bin_type != "Toggle navigation"]

        for bin_type in bin_types:
            collections.append(Collection(date=collection_date, type=bin_type))

    return collections


class Ceredigion(Scraper):
    meta = Meta(
        title="Ceredigion County Council",
        url="https://www.ceredigion.gov.uk",
        lads=("W06000008",),
        cases={
            "Test_001": {
                "house_number": "BLAEN CWMMAGWR, TRISANT, CEREDIGION, SY23 4RQ",
                "postcode": "SY23 4RQ",
            },
        },
    )
    requires = frozenset({"postcode"})
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")

        # Step 1: load initial form to get session token (ebz).
        r = await http.get(FORM_URL, timeout=30.0)
        ebz_match = re.search(r'ebz=([^&"\']+)', r.text)
        if not ebz_match:
            raise UpstreamError("Ceredigion: no session token (ebz) on form page")
        ebz = ebz_match.group(1)

        postcode_ctrl = _find_ctrl(r.text, "Postcode")
        find_btn_ctrl = _find_ctrl_button(r.text, "Find Address")
        if not postcode_ctrl or not find_btn_ctrl:
            raise UpstreamError("Ceredigion: postcode field or Find Address button missing from form")

        base_data = {
            "formid": "/Forms/REFUSE_ROUTES",
            "ebs": ebz,
            "origrequrl": "http://forms.ceredigion.gov.uk/ebase/ufsmain?formid=REFUSE_ROUTES",
            "formstack": "REFUSE_ROUTES",
            "formStateId": "1",
            "pageId": "SEARCH",
            "pageSeq": "1",
            "ufsEndUser*": "1",
            "$USERVAR2": "v.1.83",
            "PAGE:X": "0",
            "PAGE:Y": "0",
        }

        # Step 2: submit postcode.
        post_data = {
            **base_data,
            f"CTRL:{postcode_ctrl}:_:A": postcode,
            f"CTRL:{find_btn_ctrl}:_": "Find Address",
            "CTRL:R6llfHNT:_:A": "Y",
            "PAGE:F": f"CTID-{find_btn_ctrl}-_",
            "HID:inputs": (
                f"ICTRL:{postcode_ctrl}:_:A,ACTRL:{find_btn_ctrl}-_,"
                "ICTRL:R6llfHNT:_:A,APAGE:E.h,APAGE:B.h,APAGE:N.h,APAGE:S.h,APAGE:R.h"
            ),
        }
        r = await http.post(
            f"{AJAX_URL}?ebz={ebz}",
            headers=_FORM_HEADERS,
            data=post_data,
            timeout=30.0,
        )
        resp_json = r.json()

        # Step 3: find address in dropdown and select it.
        html_parts = _extract_html(resp_json)
        dropdown_ctrl = _find_select_ctrl(html_parts)
        if not dropdown_ctrl:
            raise UpstreamError("Ceredigion: no address dropdown after postcode search")

        candidates = _address_options(html_parts)
        selected = match_address(
            address,
            candidates,
            text=lambda candidate: candidate[1],
        )
        address_idx = int(selected[0])

        post_data = {
            **base_data,
            f"CTRL:{dropdown_ctrl}:_:A": str(address_idx),
            f"CTRL:{dropdown_ctrl}:_:B.h": "X",
            "CTRL:R6llfHNT:_:A": "Y",
            "PAGE:F": f"CTID-{dropdown_ctrl}-_-A",
            "HID:inputs": (
                f"ACTRL:BCLvFWji:_.h,ICTRL:{dropdown_ctrl}:_:A,"
                f"ACTRL:{dropdown_ctrl}:_:B.h,ICTRL:R6llfHNT:_:A,"
                "APAGE:E.h,APAGE:B.h,APAGE:N.h,APAGE:S.h,APAGE:R.h"
            ),
        }
        r = await http.post(
            f"{AJAX_URL}?ebz={ebz}",
            headers=_FORM_HEADERS,
            data=post_data,
            timeout=30.0,
        )
        resp_json = r.json()

        # Step 4: find and click Next button.
        html_parts = _extract_html(resp_json)
        next_ctrl = _find_ctrl_button_in_html(html_parts, "Next")
        if not next_ctrl:
            raise UpstreamError("Ceredigion: Next button missing after address selection")

        post_data = {
            **base_data,
            f"CTRL:{next_ctrl}:_": "Next",
            "CTRL:R6llfHNT:_:A": "Y",
            "PAGE:F": f"CTID-{next_ctrl}-_",
            "HID:inputs": (
                f"ACTRL:3hXVeHBY:_.h,ACTRL:{next_ctrl}-_,"
                "ICTRL:R6llfHNT:_:A,APAGE:E.h,APAGE:B.h,APAGE:N.h,APAGE:S.h,APAGE:R.h"
            ),
        }
        await http.post(
            f"{AJAX_URL}?ebz={ebz}",
            headers=_FORM_HEADERS,
            data=post_data,
            timeout=30.0,
        )

        # Step 5: re-request the form entry point to get the results page.
        r = await http.get(FORM_URL, timeout=30.0)
        return _parse_results(r.text)


SCRAPER = Ceredigion()
