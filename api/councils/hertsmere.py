"""Hertsmere: search by postcode, match an address, then read its collection weekdays."""

from __future__ import annotations

import html as _html
import json
import re

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
    next_weekday,
    soup,
)

_BASE_URL = "https://hertsmere-services.onmats.com"
_LANDING_PATH = "/w/webpage/round-search"
_SUBPAGE_ID = "PAG0000830DCFEA1"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
_FORM_HEADERS = {
    **_XHR_HEADERS,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": f"{_BASE_URL}{_LANDING_PATH}",
}


def _flatten(prefix: str, obj: object, pairs: list[tuple[str, str]]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            _flatten(f"{prefix}[{key}]", value, pairs)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _flatten(f"{prefix}[{index}]", value, pairs)
    else:
        if obj is None:
            value = ""
        elif isinstance(obj, bool):
            value = "true" if obj else "false"
        else:
            value = str(obj)
        pairs.append((prefix, value))


def _extract_typeahead_params(page_html: str) -> dict[str, object]:
    """Extract the per-load typeahead parameters embedded in the page."""
    unescaped = _html.unescape(page_html)
    marker = 'data-instance_name="system_presenter_input_relation_path_type_ahead"'
    marker_index = unescaped.find(marker)
    if marker_index == -1:
        raise ValueError("typeahead presenter not found in page")

    start_key = unescaped.find('data-params="', marker_index)
    brace = unescaped.find("{", start_key)
    if start_key == -1 or brace == -1:
        raise ValueError("typeahead parameters not found in page")

    depth = 0
    position = brace
    in_string = False
    while position < len(unescaped):
        char = unescaped[position]
        if char == '"' and unescaped[position - 1] != "\\":
            in_string = not in_string
        if not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    break
        position += 1

    return json.loads(unescaped[brace : position + 1])


class Hertsmere(Scraper):
    meta = Meta(
        title="Hertsmere Borough Council",
        url="https://www.hertsmere.gov.uk",
        lads=("E07000098",),
        cases={
            "1 Abbots Place": {
                "postcode": "WD6 5QP",
                "house_number": "1",
                "street": "Abbots Place",
            },
            "Flat 1, 1 Shenley Road": {
                "postcode": "WD6 1AA",
                "house_number": "Flat 1",
                "street": "Shenley Road",
            },
        },
    )
    requires = frozenset({"postcode"})
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")

        # Seed the session and harvest the fresh webpage token.
        r_landing = await http.get(f"{_BASE_URL}{_LANDING_PATH}", timeout=30)
        ajax_match = re.search(r"AJAX_URL\s*=\s*'([^']+)'", r_landing.text)
        dyn_match = re.search(r"AJAX_DYNAMIC_URL\s*=\s*'([^']+)'", r_landing.text)
        if not ajax_match or not dyn_match:
            raise UpstreamError("Hertsmere's lookup page did not return session tokens")

        token_parts = ajax_match.group(1).split("webpage_token=", 1)
        if len(token_parts) != 2:
            raise UpstreamError("Hertsmere's lookup page did not return a webpage token")
        token = token_parts[1]
        dyn_url = _BASE_URL + "/" + dyn_match.group(1).lstrip("/")

        # Load the dynamic page fragment containing the form and typeahead parameters.
        r_page = await http.get(dyn_url, headers=_XHR_HEADERS, timeout=30)
        page_html = r_page.json()["data"]
        try:
            typeahead_params = _extract_typeahead_params(page_html)
        except (ValueError, json.JSONDecodeError) as exc:
            raise UpstreamError(f"Could not read Hertsmere's address search form: {exc}") from exc

        # Search the postcode using the page's per-load typeahead parameters.
        pairs: list[tuple[str, str]] = []
        _flatten("levels", typeahead_params["levels"], pairs)
        pairs.append(("search_string", postcode))
        pairs.append(("display_limit", str(typeahead_params["display_limit"])))
        _flatten("presenter_settings", typeahead_params["presenter_settings"], pairs)
        _flatten("settings", typeahead_params["settings"], pairs)
        pairs.append(("context_page_id", _SUBPAGE_ID))
        ta_url = (
            f"{_BASE_URL}/w/ajax?webpage_subpage_id={_SUBPAGE_ID}"
            f"&webpage_token={token}&ajax_action=html_get_type_ahead_results"
        )
        r_typeahead = await http.post(
            ta_url,
            data=dict(pairs),
            headers=_FORM_HEADERS,
            timeout=30,
        )
        typeahead_soup = soup(r_typeahead.text)
        candidates = [
            (str(item["data-id"]), str(item.get("aria-label", "")).strip())
            for item in typeahead_soup.find_all("li")
            if item.get("data-id")
        ]
        if not candidates:
            raise AddressNotFound(f"Hertsmere lists no addresses for {postcode}")

        if address.house_number:
            remaining = list(candidates)
            picked: list[str] = []
            while remaining:
                try:
                    candidate = match_address(
                        address,
                        remaining,
                        text=lambda item: item[1],
                    )
                except AddressNotFound:
                    if not picked:
                        raise
                    break
                picked.append(candidate[0])
                remaining.remove(candidate)
        elif len(candidates) == 1:
            picked = [candidates[0][0]]
        else:
            raise InputError(
                "Several Hertsmere addresses share this postcode; provide a house number"
            )

        # Find the address-search form and its address-record field.
        page_soup = soup(page_html)
        form = None
        for candidate_form in page_soup.find_all("form", class_="page_widget_group"):
            names = {item.get("name", "") for item in candidate_form.find_all("input")}
            if any("PCF0019758" in name for name in names):
                form = candidate_form
                break
        if form is None:
            raise UpstreamError("Hertsmere's address search form was not found")

        fields = {
            str(item["name"]): str(item.get("value", ""))
            for item in form.find_all("input")
            if item.get("name")
        }
        address_key = next((key for key in fields if "PCF0019758" in key), None)
        if address_key is None:
            raise UpstreamError("Hertsmere's address search form has no address field")

        submit_url = (
            f"{_BASE_URL}{_LANDING_PATH}"
            f"?webpage_subpage_id={_SUBPAGE_ID}&webpage_token={token}"
        )

        # Stale duplicate records can have no table, so try each matched record.
        rows: list[list[str]] = []
        for record_id in picked:
            fields[address_key] = record_id
            r_submit = await http.post(
                submit_url,
                data=fields,
                headers=_FORM_HEADERS,
                timeout=30,
            )
            result_soup = soup(r_submit.json()["data"])
            table = result_soup.find("table", class_="table listing table-striped")
            tbody = table.find("tbody") if table else None
            if tbody:
                rows = [
                    [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
                    for row in tbody.find_all("tr")
                ]
                if rows:
                    break

        if not rows:
            raise AddressNotFound(
                f"Hertsmere returned no collection rounds for {address.first_line or postcode}"
            )

        collections: list[Collection] = []
        for row in rows:
            if len(row) < 2:
                continue
            round_type, day_name = row[0].strip(), row[1].strip()
            if day_name not in _DAYS:
                continue
            collections.append(
                Collection(date=next_weekday(day_name, include_today=False), type=round_type)
            )

        if not collections:
            raise InputError("Hertsmere returned no usable collection weekdays for this address")
        return collections


SCRAPER = Hertsmere()
