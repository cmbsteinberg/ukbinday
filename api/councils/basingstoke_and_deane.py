"""Basingstoke and Deane: a UPRN cookie on the bin-collections page selects the property."""

from __future__ import annotations

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    find_tag,
    parse_date,
    soup,
)

_URL = "https://www.basingstoke.gov.uk/bincollections"


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
            waste_type = find_tag(service, "h2").text.split(" ")[0]
            for schedule in service.find_all("li"):
                date_str = schedule.text.split("(")[0].strip()
                entries.append(Collection(parse_date(date_str), waste_type))

        return entries


SCRAPER = BasingstokeAndDeane()
