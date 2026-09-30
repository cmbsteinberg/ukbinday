"""New Forest: submit a postcode and UPRN through the council's multi-step form."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from api.councils._base import Address, Collection, Http, Meta, Scraper

_FORM_BASE = "https://forms.newforest.gov.uk/ufs"
_AJAX_URL = f"{_FORM_BASE}/ufsajax"
_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
_TIMEOUT = 30.0


def _find_input_ctrl(html: str, label: str) -> str | None:
    match = re.search(
        rf'<label[^>]*for="CTID-(\w+)-[^"]*"[^>]*>{re.escape(label)}</label>',
        html,
    )
    if match:
        return match.group(1)
    match = re.search(rf"CTID-(\w+)-_\s+eb-\w+-Field.*?{re.escape(label)}", html, re.DOTALL)
    return match.group(1) if match else None


def _find_button_ctrl(html: str, label: str) -> str | None:
    match = re.search(
        rf'class="[^"]*?CTID-(\w+)-_[^"]*eb-[\w-]+-Button[^"]*"[^>]*value="{re.escape(label)}"',
        html,
    )
    return match.group(1) if match else None


def _find_select_ctrl(html: str) -> str | None:
    match = re.search(r'<select[^>]*class="[^"]*?CTID-(\w+)-', html)
    return match.group(1) if match else None


def _extract_html(resp: dict[str, Any]) -> str:
    parts = []
    for ctrl in resp.get("updatedControls", []):
        parts.append(ctrl.get("html") or "")
    return "\n".join(parts)


def _parse_results(resp: dict[str, Any]) -> list[Collection]:
    html = _extract_html(resp)
    fields = re.findall(r'EditorInput\s*">([^<]+)</div>', html)
    if not fields:
        return []

    collections = []
    # Fields come in groups: address, then repeating (bin_type, date, description).
    i = 1
    while i + 2 < len(fields):
        bin_type = fields[i].strip()
        date_str = fields[i + 1].strip()
        i += 3

        try:
            day = datetime.strptime(date_str, "%A %B %d, %Y").date()
        except ValueError:
            continue

        collections.append(Collection(day, bin_type))

    return collections


class NewForest(Scraper):
    meta = Meta(
        title="New Forest District Council",
        url="https://www.newforest.gov.uk",
        lads=("E07000091",),
        cases={
            "Test_001": {"uprn": "100060482345", "postcode": "SO41 0GJ"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"User-Agent": "Mozilla/5.0"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        # Step 1: load form page to get session token.
        r = await http.get(f"{_FORM_BASE}/FIND_MY_BIN_BAR.eb", timeout=_TIMEOUT)

        ebz_match = re.search(r"ebz=([^&\"']+)", r.text)
        if not ebz_match:
            return []
        ebz = ebz_match.group(1)

        # Find postcode input and submit button control IDs.
        postcode_ctrl = _find_input_ctrl(r.text, "Postcode")
        submit_ctrl = _find_button_ctrl(r.text, "Submit")
        if not postcode_ctrl or not submit_ctrl:
            return []

        base_data = {
            "formid": "/Forms/FIND_MY_BIN_BAR",
            "ebs": ebz,
            "origrequrl": "https://forms.newforest.gov.uk/ufs/FIND_MY_BIN_BAR.eb",
            "formstack": "FIND_MY_BIN_BAR",
            "formStateId": "1",
            "pageId": "Page_1",
            "pageSeq": "1",
            "ufsEndUser*": "1",
            "PAGE:X": "0",
            "PAGE:Y": "0",
            "PAGE:E.h": "",
            "PAGE:B.h": "",
            "PAGE:N.h": "",
            "PAGE:S.h": "",
            "PAGE:R.h": "",
        }

        # Step 2: submit postcode.
        post_data = {
            **base_data,
            f"CTRL:{postcode_ctrl}:_:A": address.postcode or "",
            f"CTRL:{submit_ctrl}:_": "Submit",
            "HID:inputs": (
                f"ICTRL:{postcode_ctrl}:_:A,ACTRL:{postcode_ctrl}:_:B.h,"
                f"ACTRL:{submit_ctrl}:_,APAGE:E.h,APAGE:B.h,APAGE:N.h,APAGE:S.h,APAGE:R.h"
            ),
            "PAGE:F": f"CTID-{submit_ctrl}-_",
        }
        r = await http.post(
            f"{_AJAX_URL}?ebz={ebz}",
            headers=_FORM_HEADERS,
            data=post_data,
            timeout=_TIMEOUT,
        )
        resp = r.json()

        # Step 3: find address dropdown and submit button in response.
        html_parts = _extract_html(resp)
        addr_ctrl = _find_select_ctrl(html_parts)
        submit_ctrl2 = _find_button_ctrl(html_parts, "Submit")
        if not addr_ctrl or not submit_ctrl2:
            return []

        # Step 4: submit with UPRN.
        post_data = {
            **base_data,
            f"CTRL:{addr_ctrl}:_:A": address.need("uprn"),
            f"CTRL:{submit_ctrl2}:_": "Submit",
            "HID:inputs": (
                f"ICTRL:{addr_ctrl}:_:A,ACTRL:{addr_ctrl}:_:B.h,"
                f"ACTRL:{submit_ctrl2}:_,APAGE:E.h,APAGE:B.h,APAGE:N.h,APAGE:S.h,APAGE:R.h"
            ),
            "PAGE:F": f"CTID-{submit_ctrl2}-_",
        }
        r = await http.post(
            f"{_AJAX_URL}?ebz={ebz}",
            headers=_FORM_HEADERS,
            data=post_data,
            timeout=_TIMEOUT,
        )
        return _parse_results(r.json())


SCRAPER = NewForest()
