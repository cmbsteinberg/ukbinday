import re
from datetime import datetime

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "New Forest District Council"
DESCRIPTION = "Source for newforest.gov.uk waste collection."
URL = "https://www.newforest.gov.uk"
TEST_CASES = {
    "Test_001": {"uprn": "100060482345", "postcode": "SO41 0GJ"},
}

FORM_BASE = "https://forms.newforest.gov.uk/ufs"
AJAX_URL = f"{FORM_BASE}/ufsajax"
HEADERS = {"User-Agent": "Mozilla/5.0"}

ICON_MAP = {
    "General": "mdi:trash-can",
    "Recycle": "mdi:recycle",
    "Glass": "mdi:glass-fragile",
    "Garden": "mdi:leaf",
    "Food": "mdi:food-apple",
}


class Source:
    def __init__(self, uprn: str | int, postcode: str | None = None):
        self._uprn = str(uprn)
        self._postcode = postcode or ""

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as s:
            # Step 1: load form page to get session token
            r = await s.get(
                f"{FORM_BASE}/FIND_MY_BIN_BAR.eb",
                headers=HEADERS,
            )
            r.raise_for_status()

            ebz_match = re.search(r"ebz=([^&\"']+)", r.text)
            if not ebz_match:
                return []
            ebz = ebz_match.group(1)

            # Find postcode input and submit button control IDs
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

            # Step 2: submit postcode
            post_data = {
                **base_data,
                f"CTRL:{postcode_ctrl}:_:A": self._postcode,
                f"CTRL:{submit_ctrl}:_": "Submit",
                "HID:inputs": f"ICTRL:{postcode_ctrl}:_:A,ACTRL:{postcode_ctrl}:_:B.h,ACTRL:{submit_ctrl}:_,APAGE:E.h,APAGE:B.h,APAGE:N.h,APAGE:S.h,APAGE:R.h",
                "PAGE:F": f"CTID-{submit_ctrl}-_",
            }
            r = await s.post(
                f"{AJAX_URL}?ebz={ebz}",
                headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                data=post_data,
            )
            r.raise_for_status()
            resp = r.json()

            # Step 3: find address dropdown and submit button in response
            html_parts = _extract_html(resp)
            addr_ctrl = _find_select_ctrl(html_parts)
            submit_ctrl2 = _find_button_ctrl(html_parts, "Submit")
            if not addr_ctrl or not submit_ctrl2:
                return []

            # Step 4: submit with UPRN
            post_data = {
                **base_data,
                f"CTRL:{addr_ctrl}:_:A": self._uprn,
                f"CTRL:{submit_ctrl2}:_": "Submit",
                "HID:inputs": f"ICTRL:{addr_ctrl}:_:A,ACTRL:{addr_ctrl}:_:B.h,ACTRL:{submit_ctrl2}:_,APAGE:E.h,APAGE:B.h,APAGE:N.h,APAGE:S.h,APAGE:R.h",
                "PAGE:F": f"CTID-{submit_ctrl2}-_",
            }
            r = await s.post(
                f"{AJAX_URL}?ebz={ebz}",
                headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                data=post_data,
            )
            r.raise_for_status()
            resp = r.json()

        return _parse_results(resp)


def _find_input_ctrl(html: str, label: str) -> str | None:
    match = re.search(
        rf'<label[^>]*for="CTID-(\w+)-[^"]*"[^>]*>{re.escape(label)}</label>',
        html,
    )
    if match:
        return match.group(1)
    match = re.search(rf'CTID-(\w+)-_\s+eb-\w+-Field.*?{re.escape(label)}', html, re.DOTALL)
    return match.group(1) if match else None


def _find_button_ctrl(html: str, label: str) -> str | None:
    match = re.search(
        rf'class="CTID-(\w+)-_[^"]*eb-\w+-Button[^"]*"[^>]*value="{re.escape(label)}"',
        html,
    )
    return match.group(1) if match else None


def _find_select_ctrl(html: str) -> str | None:
    match = re.search(r'<select[^>]*class="CTID-(\w+)-', html)
    return match.group(1) if match else None


def _extract_html(resp: dict) -> str:
    parts = []
    for ctrl in resp.get("updatedControls", []):
        h = ctrl.get("html") or ""
        parts.append(h)
    return "\n".join(parts)


def _parse_results(resp: dict) -> list[Collection]:
    html = _extract_html(resp)
    fields = re.findall(r'EditorInput\s*">([^<]+)</div>', html)
    if not fields:
        return []

    entries = []
    # Fields come in groups: address, then repeating (bin_type, date, description)
    # Skip the first field (address)
    i = 1
    while i + 2 < len(fields):
        bin_type = fields[i].strip()
        date_str = fields[i + 1].strip()
        i += 3

        try:
            dt = datetime.strptime(date_str, "%A %B %d, %Y").date()
        except ValueError:
            continue

        icon = None
        for key, val in ICON_MAP.items():
            if key.lower() in bin_type.lower():
                icon = val
                break
        entries.append(Collection(date=dt, t=bin_type, icon=icon))

    return sorted(entries, key=lambda c: c.date)
