"""Sevenoaks: select a property by ID, then fetch and parse its waste schedule."""

from __future__ import annotations

import json
import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    soup,
)

_BASE_URL = "https://sevenoaks-dc-host01.oncreate.app"
_WEBPAGE_TOKEN = "978e3e1fd8936f98a424235001d93f261cc2458668d650a18f3a1155494d063d"
_SUBPAGE_ID = "PAG0000639GBDJR1"
_CELL_ID = "PCL0004972GBDJR1"
_LANDING_PATH = "/w/webpage/waste-collection-day"

_DATE_RE = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]+ (\d{1,2} [A-Z][a-z]+ \d{4})")
_SECTIONS = (
    ("Fortnightly garden waste collection", "Garden waste"),
    ("Weekly recycling and general waste collection", "Recycling and general waste"),
    ("Weekly food waste collection", "Food waste"),
)

_EVENT_URL = (
    f"{_BASE_URL}{_LANDING_PATH}"
    f"?webpage_subpage_id={_SUBPAGE_ID}"
    f"&webpage_token={_WEBPAGE_TOKEN}"
    "&widget_action=handle_event"
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _parse_schedule(html: str, property_id: str) -> list[Collection]:
    if not html:
        raise InputError(
            f"No collection data returned for property_id {property_id} — "
            "please check your property_id is correct"
        )

    text = soup(html).get_text(" ", strip=True)
    entries: list[Collection] = []

    for heading, waste_type in _SECTIONS:
        idx = text.lower().find(heading.lower())
        if idx == -1:
            continue
        segment = text[idx:]
        for other_heading, _ in _SECTIONS:
            if other_heading == heading:
                continue
            other_idx = segment.lower().find(other_heading.lower())
            if other_idx != -1:
                segment = segment[:other_idx]

        match = _DATE_RE.search(segment)
        if not match:
            continue
        try:
            next_date = datetime.strptime(match.group(1), "%d %B %Y").date()
        except ValueError:
            continue
        entries.append(Collection(date=next_date, type=waste_type))

    if not entries:
        raise InputError(
            f"No collection dates found for property_id {property_id} — the address may not "
            "have a domestic waste collection service, or the property_id is incorrect"
        )

    return entries


class Sevenoaks(Scraper):
    meta = Meta(
        title="Sevenoaks District Council",
        url="https://www.sevenoaks.gov.uk",
        lads=("E07000111",),
        cases={
            "1 Crawshay Close TN13 3EJ": {"property_id": "51621"},
            "10 Mill Lane TN14 5BX": {"property_id": "15147"},
        },
    )
    requires = frozenset({"property_id"})
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        property_id = address.need("property_id")

        await http.get(f"{_BASE_URL}{_LANDING_PATH}")

        r_select = await http.post(
            _EVENT_URL,
            data={
                "code_action": "address_selected",
                "code_params": json.dumps({"selected": property_id}),
                "action_cell_id": _CELL_ID,
                "action_page_id": _SUBPAGE_ID,
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        select_json = r_select.json()

        schedule_url = select_json.get("response", {}).get("url")
        if select_json.get("result") != "success" or not schedule_url:
            raise InputError(
                f"Property lookup failed for property_id {property_id} — "
                "please check your property_id is correct"
            )

        r_schedule = await http.get(
            schedule_url,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        html = r_schedule.json().get("data", "")
        return _parse_schedule(html, property_id)


SCRAPER = Sevenoaks()
