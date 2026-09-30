"""Basingstoke and Deane: a UPRN cookie on the bin-collections page selects the property."""

from __future__ import annotations

import logging
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    soup,
)

_URL = "https://www.basingstoke.gov.uk/bincollections"
_LOGGER = logging.getLogger(__name__)


class BasingstokeAndDeane(Scraper):
    meta = Meta(
        title="Basingstoke and Deane Borough Council",
        url="https://basingstoke.gov.uk",
        lads=("E07000084",),
        cases={
            "Test_001": {"uprn": "100060234732"},
            "Test_002": {"uprn": "100060218986"},
            "Test_003": {"uprn": "100060235836"},
        },
    )
    requires = frozenset({"uprn"})
    headers = {"user-agent": "Mozilla/5.0"}
    transport = Transport.CURL_CFFI
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        http.cookies.set("cookie_control_popup", "N", domain="www.basingstoke.gov.uk")
        http.cookies.set("WhenAreMyBinsCollected", uprn, domain="www.basingstoke.gov.uk")
        r = await http.get(_URL)

        page = soup(r.text)
        services = page.find_all("div", class_="service")
        entries: list[Collection] = []

        for service in services:
            waste_type = service.find("h2").text.split(" ")[0]
            for schedule in service.find_all("li"):
                date_str = schedule.text.split("(")[0].strip()
                try:
                    day = datetime.strptime(date_str, "%A, %d %B %Y").date()
                except ValueError as exc:
                    _LOGGER.warning(
                        "Failed to parse date '%s' for wastetype %s: %s",
                        date_str,
                        waste_type,
                        exc,
                    )
                    continue

                entries.append(Collection(day, waste_type))

        return entries


SCRAPER = BasingstokeAndDeane()
