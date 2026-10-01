"""Netcall Liberty Create portals (`*.onmats.com`, `waste.digital.<council>.gov.uk`), used by
Hertsmere and Gedling.

Both councils run the same postcode-search page:

1. `GET <landing>` seeds the session and carries `AJAX_URL` (with the page's
   `webpage_token`) and `AJAX_DYNAMIC_URL`; the dynamic URL returns the page's form HTML.
2. The form embeds per-load typeahead parameters. Posting them back with the postcode to
   `/w/ajax?...ajax_action=html_get_type_ahead_results` lists the addresses (`li[data-id]`).
3. Posting the form with the chosen record id in the address field answers with JSON: either
   the result HTML in `data`, or a `redirect_url` to a results page whose own dynamic
   fragment holds it.

What differs per council is the ids and how the result table reads, in
`LibertyCreateConfig`: `parse` turns the result HTML into collections.
"""

from __future__ import annotations

import html as _html
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from bs4 import BeautifulSoup

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Platform,
    UpstreamError,
    match_address,
    soup,
)

_TIMEOUT = 30
_XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


@dataclass(frozen=True, slots=True, kw_only=True)
class LibertyCreateConfig:
    base_url: str
    """"https://hertsmere-services.onmats.com"."""
    landing_path: str
    """The postcode-search page: "/w/webpage/round-search"."""
    subpage_id: str
    """The `webpage_subpage_id` of the search form's page."""
    address_field: str
    """Fragment id (PCF...) that appears in the name of the form's address-record input."""
    parse: Callable[[BeautifulSoup], list[Collection]]
    """Reads the collections from the result HTML; empty when the record has none."""


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


class LibertyCreate(Platform[LibertyCreateConfig]):
    requires = frozenset({"postcode"})
    headers: Mapping[str, str] = MappingProxyType(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
    )

    async def _fragment(self, http: Http, page_url: str) -> tuple[str, str]:
        """Load a portal page; return its webpage token and its dynamic HTML fragment."""
        name = self.meta.title
        page = await http.get(page_url, timeout=_TIMEOUT)
        ajax_match = re.search(r"AJAX_URL\s*=\s*'([^']+)'", page.text)
        dyn_match = re.search(r"AJAX_DYNAMIC_URL\s*=\s*'([^']+)'", page.text)
        if not ajax_match or not dyn_match:
            raise UpstreamError(f"{name}'s lookup page did not return session tokens")
        token_parts = ajax_match.group(1).split("webpage_token=", 1)
        if len(token_parts) != 2:
            raise UpstreamError(f"{name}'s lookup page did not return a webpage token")
        dyn_url = self.config.base_url + "/" + dyn_match.group(1).lstrip("/")
        r_page = await http.get(dyn_url, headers=_XHR_HEADERS, timeout=_TIMEOUT)
        return token_parts[1], r_page.json()["data"]

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        cfg = self.config
        name = self.meta.title
        postcode = address.need("postcode")
        landing = f"{cfg.base_url}{cfg.landing_path}"
        form_headers = {
            **_XHR_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": landing,
        }

        # Seed the session and load the form with its per-load typeahead parameters.
        token, page_html = await self._fragment(http, landing)
        try:
            typeahead_params = _extract_typeahead_params(page_html)
        except (ValueError, json.JSONDecodeError) as exc:
            raise UpstreamError(f"Could not read {name}'s address search form: {exc}") from exc

        # Search the postcode using those parameters.
        pairs: list[tuple[str, str]] = []
        _flatten("levels", typeahead_params["levels"], pairs)
        pairs.append(("search_string", postcode))
        pairs.append(("display_limit", str(typeahead_params["display_limit"])))
        _flatten("presenter_settings", typeahead_params["presenter_settings"], pairs)
        _flatten("settings", typeahead_params["settings"], pairs)
        pairs.append(("context_page_id", cfg.subpage_id))
        ta_url = (
            f"{cfg.base_url}/w/ajax?webpage_subpage_id={cfg.subpage_id}"
            f"&webpage_token={token}&ajax_action=html_get_type_ahead_results"
        )
        r_typeahead = await http.post(ta_url, data=dict(pairs), headers=form_headers, timeout=_TIMEOUT)
        candidates = [
            (str(item["data-id"]), str(item.get("aria-label", "")).strip())
            for item in soup(r_typeahead.text).find_all("li")
            if item.get("data-id")
        ]
        if not candidates:
            raise AddressNotFound(f"{name} lists no addresses for {postcode}")

        if address.house_number:
            remaining = list(candidates)
            picked: list[str] = []
            while remaining:
                try:
                    candidate = match_address(address, remaining, text=lambda item: item[1])
                except AddressNotFound:
                    if not picked:
                        raise
                    break
                picked.append(candidate[0])
                remaining.remove(candidate)
        elif len(candidates) == 1:
            picked = [candidates[0][0]]
        else:
            raise InputError(f"Several {name} addresses share this postcode; provide a house number")

        # Find the address-search form and its address-record field.
        form = None
        for candidate_form in soup(page_html).find_all("form", class_="page_widget_group"):
            names = {str(item.get("name", "")) for item in candidate_form.find_all("input")}
            if any(cfg.address_field in name for name in names):
                form = candidate_form
                break
        if form is None:
            raise UpstreamError(f"{name}'s address search form was not found")
        fields = {
            str(item["name"]): str(item.get("value", ""))
            for item in form.find_all("input")
            if item.get("name")
        }
        address_key = next((key for key in fields if cfg.address_field in key), None)
        if address_key is None:
            raise UpstreamError(f"{name}'s address search form has no address field")

        submit_url = f"{landing}?webpage_subpage_id={cfg.subpage_id}&webpage_token={token}"

        # Stale duplicate records can have no collections, so try each matched record.
        for record_id in picked:
            fields[address_key] = record_id
            r_submit = await http.post(submit_url, data=fields, headers=form_headers, timeout=_TIMEOUT)
            body = r_submit.json()
            if redirect := body.get("redirect_url"):
                _, result_html = await self._fragment(http, cfg.base_url + redirect)
            else:
                result_html = body["data"]
            if collections := cfg.parse(soup(result_html)):
                return collections

        raise AddressNotFound(f"{name} returned no collections for {address.first_line or postcode}")
