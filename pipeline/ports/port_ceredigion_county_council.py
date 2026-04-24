import re
from datetime import datetime

import httpx

from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Ceredigion County Council"
DESCRIPTION = "Source for ceredigion.gov.uk waste collection."
URL = "https://www.ceredigion.gov.uk"
# house_number = full address text as shown in the dropdown, postcode = postcode
TEST_CASES = {
    "Test_001": {
        "house_number": "BLAEN CWMMAGWR, TRISANT, CEREDIGION, SY23 4RQ",
        "postcode": "SY23 4RQ",
    },
}

FORM_URL = "https://forms.ceredigion.gov.uk/ebase/REFUSE_ROUTES.eb"
AJAX_URL = "https://forms.ceredigion.gov.uk/ebase/ufsajax"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}

ICON_MAP = {
    "Clear recycling bag": "mdi:recycle",
    "Food": "mdi:food-apple",
    "Non-recyclable": "mdi:trash-can",
    "Glass": "mdi:glass-fragile",
    "Garden": "mdi:leaf",
    "Nappy": "mdi:baby-carriage",
}


class Source:
    def __init__(self, house_number: str | None = None, postcode: str | None = None):
        self._address = house_number or ""
        self._postcode = postcode or ""

    async def fetch(self) -> list[Collection]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as s:
            # Step 1: load initial form to get session token (ebz)
            r = await s.get(
                "https://forms.ceredigion.gov.uk/ebase/ufsmain?formid=REFUSE_ROUTES",
                headers=HEADERS,
            )
            r.raise_for_status()

            ebz_match = re.search(r'ebz=([^&"\']+)', r.text)
            if not ebz_match:
                return []
            ebz = ebz_match.group(1)

            # Find control IDs from the form HTML
            postcode_ctrl = _find_ctrl(r.text, "Postcode")
            find_btn_ctrl = _find_ctrl_button(r.text, "Find Address")
            if not postcode_ctrl or not find_btn_ctrl:
                return []

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

            # Step 2: submit postcode
            post_data = {
                **base_data,
                f"CTRL:{postcode_ctrl}:_:A": self._postcode,
                f"CTRL:{find_btn_ctrl}:_": "Find Address",
                "CTRL:R6llfHNT:_:A": "Y",
                "PAGE:F": f"CTID-{find_btn_ctrl}-_",
                "HID:inputs": f"ICTRL:{postcode_ctrl}:_:A,ACTRL:{find_btn_ctrl}:_,ICTRL:R6llfHNT:_:A,APAGE:E.h,APAGE:B.h,APAGE:N.h,APAGE:S.h,APAGE:R.h",
            }
            r = await s.post(
                f"{AJAX_URL}?ebz={ebz}",
                headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                data=post_data,
            )
            r.raise_for_status()
            resp_json = r.json()

            # Step 3: find address in dropdown and select it
            html_parts = _extract_html(resp_json)
            dropdown_ctrl = _find_select_ctrl(html_parts)
            if not dropdown_ctrl:
                return []

            address_idx = _find_address_index(html_parts, self._address)

            post_data = {
                **base_data,
                f"CTRL:{dropdown_ctrl}:_:A": str(address_idx),
                f"CTRL:{dropdown_ctrl}:_:B.h": "X",
                "CTRL:R6llfHNT:_:A": "Y",
                "PAGE:F": f"CTID-{dropdown_ctrl}-_-A",
                "HID:inputs": f"ACTRL:BCLvFWji:_.h,ICTRL:{dropdown_ctrl}:_:A,ACTRL:{dropdown_ctrl}:_:B.h,ICTRL:R6llfHNT:_:A,APAGE:E.h,APAGE:B.h,APAGE:N.h,APAGE:S.h,APAGE:R.h",
            }
            r = await s.post(
                f"{AJAX_URL}?ebz={ebz}",
                headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                data=post_data,
            )
            r.raise_for_status()
            resp_json = r.json()

            # Step 4: find and click Next button
            html_parts = _extract_html(resp_json)
            next_ctrl = _find_ctrl_button_in_html(html_parts, "Next")
            if not next_ctrl:
                return []

            post_data = {
                **base_data,
                f"CTRL:{next_ctrl}:_": "Next",
                "CTRL:R6llfHNT:_:A": "Y",
                "PAGE:F": f"CTID-{next_ctrl}-_",
                "HID:inputs": f"ACTRL:3hXVeHBY:_.h,ACTRL:{next_ctrl}:_,ICTRL:R6llfHNT:_:A,APAGE:E.h,APAGE:B.h,APAGE:N.h,APAGE:S.h,APAGE:R.h",
            }
            r = await s.post(
                f"{AJAX_URL}?ebz={ebz}",
                headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                data=post_data,
            )
            r.raise_for_status()

            # Step 5: get results page
            r = await s.get(
                f"{FORM_URL}?Reset=false&ebd=0&ebz={ebz}",
                headers=HEADERS,
            )
            r.raise_for_status()

        return _parse_results(r.text)


def _find_ctrl(html: str, label: str) -> str | None:
    match = re.search(
        rf'data-ebv-desc=["\']({re.escape(label)})["\'].*?CTID-(\w+)-',
        html, re.DOTALL,
    )
    if match:
        return match.group(2)
    match = re.search(rf'CTID-(\w+)-_\s+eb-\w+-Field.*?{re.escape(label)}', html, re.DOTALL)
    return match.group(1) if match else None


def _find_ctrl_button(html: str, label: str) -> str | None:
    match = re.search(rf'CTID-(\w+)-_[^>]*eb-\w+-Button[^>]*value=["\']({re.escape(label)})["\']', html)
    return match.group(1) if match else None


def _find_ctrl_button_in_html(html_parts: str, label: str) -> str | None:
    match = re.search(rf'CTID-(\w+)-_[^>]*eb-\w+-Button[^>]*value=["\']({re.escape(label)})["\']', html_parts)
    return match.group(1) if match else None


def _find_select_ctrl(html: str) -> str | None:
    match = re.search(r'<select[^>]*class="CTID-(\w+)-', html)
    return match.group(1) if match else None


def _extract_html(resp_json: dict) -> str:
    parts = []
    for ctrl in resp_json.get("updatedControls", []):
        h = ctrl.get("html", "")
        if h:
            parts.append(h)
    return "\n".join(parts)


def _find_address_index(html: str, address: str) -> int:
    options = re.findall(r'<option[^>]*value="(\d+)"[^>]*>([^<]+)</option>', html)
    address_upper = address.upper().strip()
    for val, text in options:
        if text.strip().upper() == address_upper:
            return int(val)
    return 0


def _parse_results(html: str) -> list[Collection]:
    entries = []
    now = datetime.now()

    blocks = re.split(r"(?=Next collection:)", html)
    for block in blocks[1:]:
        date_match = re.search(
            r"Next collection:</strong>\s*(\w+day)\s+(\d+)(?:st|nd|rd|th)?\s+(\w+)",
            block,
        )
        if not date_match:
            continue

        _, day, month = date_match.groups()
        year = now.year
        try:
            dt = datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()
        except ValueError:
            continue
        if dt < now.date():
            dt = datetime.strptime(f"{day} {month} {year + 1}", "%d %B %Y").date()

        bin_types = re.findall(r'aria-label="([^"]+)"', block)
        bin_types = [t for t in bin_types if t not in ("Toggle navigation",)]

        for bt in bin_types:
            icon = ICON_MAP.get(bt)
            entries.append(Collection(date=dt, t=bt, icon=icon))

    return sorted(entries, key=lambda c: c.date)
