"""Rother: POST the UPRN to its WordPress AJAX endpoint and parse the returned bin dates."""

from __future__ import annotations

from collections.abc import Mapping

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    parse_date,
    soup,
)

_API_URL = "https://www.rother.gov.uk/wp-admin/admin-ajax.php"
_BIN_TYPES = ("refuse", "garden", "recycling")


def _response_data(payload: object) -> str:
    if not isinstance(payload, Mapping) or "success" not in payload or "data" not in payload:
        raise UpstreamError("Rother District Council returned an invalid response")
    if not payload["success"]:
        raise UpstreamError("Rother District Council returned a non-successful response")
    data = payload["data"]
    if not isinstance(data, str):
        raise UpstreamError("Rother District Council returned an invalid response")
    return data


class Rother(Scraper):
    meta = Meta(
        title="Rother District Council",
        url="https://www.rother.gov.uk",
        lads=("E07000064",),
        cases={
            "Test_01": {"uprn": "10002653856"},
            "Test_02": {"uprn": "100060102891"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": "Mozilla/5.0",
    }
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.post(
            _API_URL,
            data={"action": "get_address_data", "uprn": address.need("uprn")},
            timeout=10,
        )
        payload = response.json()
        page = soup(_response_data(payload))

        collections = []
        for bin_type in _BIN_TYPES:
            date_span = page.find("span", class_=f"find-my-nearest-bindays-{bin_type}")
            if date_span is None:
                continue

            date_text = date_span.text.strip()
            if date_text.startswith("Sign up"):
                continue

            try:
                collection_date = parse_date(date_text)
            except ValueError:
                continue
            collections.append(Collection(collection_date, bin_type))

        if not collections:
            raise UpstreamError("Unable to find any bin collection schedules")
        return collections


SCRAPER = Rother()
