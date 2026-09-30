"""South Lanarkshire: submit a postcode and UPRN to the dashboard and parse its embedded schedule."""

from __future__ import annotations

import json
from datetime import datetime

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    soup,
)

_DASHBOARD_URL = "https://wasteservices.southlanarkshire.gov.uk/PublicDashboard"
_REQUEST_TIMEOUT = 30


def _extract_data_sources(html: str) -> list[list[object]]:
    marker = '"dataSource": ejs.data.DataUtil.parse.isJson('
    search_from = 0
    data_sources: list[list[object]] = []
    decoder = json.JSONDecoder()

    while True:
        idx = html.find(marker, search_from)
        if idx == -1:
            break
        start = idx + len(marker)
        try:
            data, _ = decoder.raw_decode(html, idx=start)
            if isinstance(data, list):
                data_sources.append(data)
        except ValueError:
            pass
        search_from = idx + 1

    return data_sources


def _extract_appointments(html: str) -> list[object]:
    for data in _extract_data_sources(html):
        if data and isinstance(data[0], dict) and "Subject" in data[0] and "StartTime" in data[0]:
            return data
    return []


def _extract_premises(html: str) -> list[object]:
    for data in _extract_data_sources(html):
        if data and isinstance(data[0], dict) and "Premises" in data[0]:
            return data
    return []


class SouthLanarkshire(Scraper):
    meta = Meta(
        title="South Lanarkshire Council",
        url=_DASHBOARD_URL,
        lads=("S12000029",),
        cases={
            "1 Clincarthill Road, Glasgow, G73 2LF": {
                "postcode": "G73 2LF",
                "uprn": "484129473",
            },
            "55 Chapel Court, Glasgow, G73 1UR": {
                "postcode": "G73 1UR",
                "uprn": "484000600",
            },
            "Flat 1 10, Burnside Lane, Hamilton, ML3 6QP": {
                "postcode": "ML3 6QP",
                "uprn": "484073020",
            },
        },
    )
    requires = frozenset({"postcode", "uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").strip().upper()
        uprn = str(int(address.need("uprn")))

        response = await http.get(_DASHBOARD_URL, timeout=_REQUEST_TIMEOUT)
        page = soup(response.text)
        token_input = page.find("input", {"name": "__RequestVerificationToken"})
        if token_input is None:
            raise InputError(
                "could not load the South Lanarkshire dashboard form; the council site may have changed."
            )
        token = token_input["value"]

        response = await http.post(
            _DASHBOARD_URL,
            params={"handler": "SelectPrem"},
            data={
                "SelectedPostcode": postcode,
                "SelectedPremises": uprn,
                "__RequestVerificationToken": token,
            },
            timeout=_REQUEST_TIMEOUT,
        )

        premises = _extract_premises(response.text)
        appointments = _extract_appointments(response.text)
        if not appointments:
            suggestions = [
                f"{premise['Premises']} (UPRN {premise['UPRN']})"
                for premise in premises
                if isinstance(premise, dict)
                and premise.get("Premises")
                and premise.get("UPRN") is not None
            ]
            if suggestions:
                raise AddressNotFound(f"No appointments for UPRN {uprn}", suggestions)
            raise AddressNotFound(f"No appointments for UPRN {uprn}")

        collections: list[Collection] = []
        for appointment in appointments:
            if not isinstance(appointment, dict):
                continue
            try:
                start_time = appointment["StartTime"]
                subject = appointment["Subject"]
                if not isinstance(start_time, str) or not isinstance(subject, str):
                    continue
                collection_date = datetime.fromisoformat(start_time).date()
            except (KeyError, ValueError):
                continue
            collections.append(Collection(collection_date, subject))

        return collections


SCRAPER = SouthLanarkshire()
