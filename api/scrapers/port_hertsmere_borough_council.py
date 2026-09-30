"""Hertsmere Borough Council bin collections (Oncreate/Liberty Create backend).

Lookup chain: GET round-search landing (session cookie) -> GET AJAX dynamic
page (fresh webpage_token + search form fields + typeahead params) ->
POST html_get_type_ahead_results (postcode -> address record ids) ->
POST search form with picked record id -> "Collection days" table of
[Round type, Collection Day, Round name].

Data-quality note: the source publishes collection *weekdays* only (e.g.
"Wednesday"), not dates. Each round type is returned once, dated at the next
upcoming occurrence of its weekday (same convention as
port_hillingdon_council). No multi-week projection is fabricated: the
council's own round-search page carries no date information at all.

Source of truth: pipeline/ports/. api/scrapers/ copies are rebuilt every sync.
"""

import html as _html
import json
import logging
import re
from datetime import date, timedelta
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentNotFound

TITLE = "Hertsmere Borough Council"
DESCRIPTION = "Source for hertsmere.gov.uk bin collections (collection weekdays only — dates are next-occurrence projections)."
URL = "https://www.hertsmere.gov.uk"
TEST_CASES = {
    "1 Abbots Place, Borehamwood WD6 5QP": {
        "postcode": "WD6 5QP",
        "house_number": "1 Abbots Place",
    },
    "Flat 1, 1 Shenley Road, Borehamwood WD6 1AA": {
        "postcode": "WD6 1AA",
        "house_number": "Flat 1, 1 Shenley Road",
    },
}

_LOGGER = logging.getLogger(__name__)

_BASE_URL = "https://hertsmere-services.onmats.com"
_LANDING_PATH = "/w/webpage/round-search"
_SUBPAGE_ID = "PAG0000830DCFEA1"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

ICON_MAP = {
    "Green": Icons.GARDEN,
    "Refuse": Icons.GENERAL_WASTE,
    "Food": Icons.BIO_KITCHEN,
    "Recycling": Icons.RECYCLING,
}

PARAM_DESCRIPTIONS = {
    "en": {
        "postcode": "Postcode of the property (e.g. WD6 5QP)",
        "house_number": "Leading part of the address as shown in the lookup (e.g. '1 Abbots Place' or 'Flat 1, 1 Shenley Road')",
    }
}

HOW_TO_GET_ARGUMENTS_DESCRIPTION = {
    "en": "Visit https://hertsmere-services.onmats.com/w/webpage/round-search, enter your postcode and select your address; use the postcode and the leading part of the address shown.",
}


def _next_weekday(day_name: str) -> date:
    today = date.today()
    delta = (_DAYS.index(day_name) - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _flatten(prefix: str, obj: object, pairs: list) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            _flatten(f"{prefix}[{key}]", value, pairs)
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            _flatten(f"{prefix}[{idx}]", value, pairs)
    else:
        if obj is None:
            obj = ""
        elif isinstance(obj, bool):
            obj = "true" if obj else "false"
        else:
            obj = str(obj)
        pairs.append((prefix, obj))


def _extract_typeahead_params(page_html: str) -> dict:
    """Pull the (per-load, encrypted) typeahead params out of the page HTML."""
    unescaped = _html.unescape(page_html)
    marker = 'data-instance_name="system_presenter_input_relation_path_type_ahead"'
    idx = unescaped.find(marker)
    if idx == -1:
        raise ValueError("typeahead presenter not found in page")
    start_key = unescaped.find('data-params="', idx)
    brace = unescaped.find("{", start_key)
    depth, pos, in_str = 0, brace, False
    while pos < len(unescaped):
        char = unescaped[pos]
        if char == '"' and unescaped[pos - 1] != "\\":
            in_str = not in_str
        if not in_str:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    break
        pos += 1
    return json.loads(unescaped[brace : pos + 1])


def _matches(label: str, house_number: str) -> bool:
    lab, hn = label.strip().lower(), house_number.strip().lower()
    return lab == hn or lab.startswith(hn + " ") or lab.startswith(hn + ",")


class Source:
    def __init__(self, postcode: str, house_number: str = ""):
        self._postcode = postcode.strip()
        self._house_number = house_number.strip()

    async def fetch(self) -> list[Collection]:
        if not self._postcode:
            raise SourceArgumentNotFound(
                "postcode",
                self._postcode,
                "a postcode is required for the Hertsmere address lookup",
            )

        async with httpx.AsyncClient(
            follow_redirects=True, headers={"User-Agent": _USER_AGENT}, timeout=30
        ) as session:
            # Step 1: seed the session, harvest the fresh webpage_token.
            r_landing = await session.get(f"{_BASE_URL}{_LANDING_PATH}")
            r_landing.raise_for_status()
            ajax_match = re.search(r"AJAX_URL\s*=\s*'([^']+)'", r_landing.text)
            dyn_match = re.search(
                r"AJAX_DYNAMIC_URL\s*=\s*'([^']+)'", r_landing.text
            )
            if not ajax_match or not dyn_match:
                raise SourceArgumentNotFound(
                    "postcode",
                    self._postcode,
                    "the council lookup page did not return session tokens",
                )
            token = ajax_match.group(1).split("webpage_token=")[1]
            dyn_url = _BASE_URL + "/" + dyn_match.group(1).lstrip("/")

            xhr = {"X-Requested-With": "XMLHttpRequest"}

            # Step 2: load the dynamic page fragment (form fields + typeahead params).
            r_page = await session.get(dyn_url, headers=xhr)
            r_page.raise_for_status()
            page_html: str = r_page.json()["data"]
            try:
                ta_params = _extract_typeahead_params(page_html)
            except (ValueError, json.JSONDecodeError) as exc:
                raise SourceArgumentNotFound(
                    "postcode",
                    self._postcode,
                    f"could not read the address search form: {exc}",
                ) from exc

            # Step 3: typeahead lookup by postcode.
            pairs: list = []
            _flatten("levels", ta_params["levels"], pairs)
            pairs.append(("search_string", self._postcode))
            pairs.append(("display_limit", str(ta_params["display_limit"])))
            _flatten("presenter_settings", ta_params["presenter_settings"], pairs)
            _flatten("settings", ta_params["settings"], pairs)
            pairs.append(("context_page_id", _SUBPAGE_ID))
            ta_url = (
                f"{_BASE_URL}/w/ajax?webpage_subpage_id={_SUBPAGE_ID}"
                f"&webpage_token={token}&ajax_action=html_get_type_ahead_results"
            )
            r_ta = await session.post(
                ta_url,
                content=urlencode(pairs),
                headers={
                    **xhr,
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Referer": f"{_BASE_URL}{_LANDING_PATH}",
                },
            )
            r_ta.raise_for_status()
            ta_soup = BeautifulSoup(r_ta.text, "html.parser")
            candidates = [
                (li.get("data-id"), li.get("aria-label", "").strip())
                for li in ta_soup.find_all("li")
                if li.get("data-id")
            ]
            if not candidates:
                raise SourceArgumentNotFound(
                    "postcode",
                    self._postcode,
                    "the council lookup returned no addresses for this postcode",
                )

            if self._house_number:
                picked = [
                    rec_id
                    for rec_id, label in candidates
                    if _matches(label, self._house_number)
                ]
                if not picked:
                    raise SourceArgumentNotFound(
                        "house_number",
                        self._house_number,
                        "no address at this postcode starts with the given house_number",
                    )
            elif len(candidates) == 1:
                picked = [candidates[0][0]]
            else:
                raise SourceArgumentNotFound(
                    "house_number",
                    self._house_number,
                    "several addresses share this postcode — please provide house_number",
                )

            # Step 4: submit the search form for the picked record(s). Stale
            # duplicate records can return an empty round table, so fall
            # through to the next match until one yields rows.
            soup = BeautifulSoup(page_html, "html.parser")
            form = None
            for candidate_form in soup.find_all("form", class_="page_widget_group"):
                names = {
                    inp.get("name", "")
                    for inp in candidate_form.find_all("input")
                }
                if any("PCF0019758" in name for name in names):
                    form = candidate_form
                    break
            if form is None:
                raise SourceArgumentNotFound(
                    "postcode",
                    self._postcode,
                    "the council address search form was not found",
                )
            fields = {
                inp.get("name"): inp.get("value", "")
                for inp in form.find_all("input")
                if inp.get("name")
            }
            addr_key = next(k for k in fields if "PCF0019758" in k)
            submit_url = (
                f"{_BASE_URL}{_LANDING_PATH}"
                f"?webpage_subpage_id={_SUBPAGE_ID}&webpage_token={token}"
            )

            rows: list = []
            for record_id in picked:
                fields[addr_key] = record_id
                r_submit = await session.post(
                    submit_url,
                    content=urlencode(fields),
                    headers={
                        **xhr,
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Referer": f"{_BASE_URL}{_LANDING_PATH}",
                    },
                )
                r_submit.raise_for_status()
                result_soup = BeautifulSoup(
                    r_submit.json()["data"], "html.parser"
                )
                table = result_soup.find("table", class_="table listing table-striped")
                if table and table.find("tbody"):
                    rows = [
                        [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                        for row in table.find("tbody").find_all("tr")
                    ]
                    if rows:
                        break

            if not rows:
                raise SourceArgumentNotFound(
                    "house_number" if self._house_number else "postcode",
                    self._house_number or self._postcode,
                    "the council lookup returned no collection rounds for this address",
                )

            return self._parse(rows)

    def _parse(self, rows: list) -> list[Collection]:
        entries: list[Collection] = []
        for row in rows:
            if len(row) < 2:
                continue
            round_type, day_name = row[0].strip(), row[1].strip()
            if day_name not in _DAYS:
                _LOGGER.warning("Skipping unparseable collection day: %r", day_name)
                continue
            icon = next(
                (
                    icon_val
                    for key, icon_val in ICON_MAP.items()
                    if key.lower() in round_type.lower()
                ),
                None,
            )
            entries.append(
                Collection(date=_next_weekday(day_name), t=round_type, icon=icon)
            )

        if not entries:
            raise SourceArgumentNotFound(
                "postcode",
                self._postcode,
                "no usable collection weekdays found for this address",
            )
        return entries
