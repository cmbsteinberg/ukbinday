"""Whitespace WRP ("Waste & Recycling Portal"), `*-wrp.whitespacews.com`.

Every portal runs the same flow:

1. GET the landing page and take the "View my collections" link (`seq=1`,
   `serviceID=A`), which carries a per-session `Track=` token.
2. POST the address form to that link with `seq=2`.
3. Pick the property from `#property_list`.
4. GET the property page and read `section#scheduled-collections`, where each
   list holds `[icon, date, service name]` items.

What differs per council is data, in `WhitespaceConfig`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from api.councils._base import (
    Address,
    AddressNotFound,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
    text_of,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class WhitespaceConfig:
    base_url: str
    match: Literal["address", "first"] = "address"
    """"first" takes the first listed property, for portals that list only the
    property matching the postcode and number. "address" uses `match_address`."""
    strip_suffixes: tuple[str, ...] = ()
    """Removed from service names: " Collection Service"."""
    rename: Mapping[str, str] = field(default_factory=dict)
    """Service name (after stripping) -> the name to show."""
    only_renamed: bool = False
    """Drop services missing from `rename` (portals that list non-bin services too)."""
    upper: bool = False
    """Upper-case service names (after stripping and before `rename`)."""
    date_format: str = "%d/%m/%Y"


def _landing_link(page: BeautifulSoup) -> str:
    links = [a for a in page.find_all("a", href=True) if "seq=1" in a["href"]]
    if not links:
        raise UpstreamError("Whitespace landing page has no collections link")
    for a in links:
        if a.get_text(strip=True).lower() == "view my collections":
            return str(a["href"])
    for a in links:
        if "serviceID=A" in a["href"]:
            return str(a["href"])
    return str(links[0]["href"])


class Whitespace(Scraper):
    requires = frozenset({"postcode", "house_number"})

    def __init__(self, meta: Meta, config: WhitespaceConfig, *, icons: Mapping[str, str] | None = None) -> None:
        self.meta = meta
        self.config = config
        if icons is not None:
            self.icons = icons

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        cfg = self.config
        r = await http.get(cfg.base_url.rstrip("/") + "/")
        link = _landing_link(soup(r.text))

        r = await http.post(
            link.replace("seq=1", "seq=2"),
            data={
                "address_name_number": address.house_number or "",
                "address_street": "",
                "street_town": "",
                "address_postcode": address.need("postcode"),
            },
        )
        page = soup(r.text)
        container = page.find(id="property_list") or page
        anchors = [
            a for a in container.find_all("a", href=True)
            if isinstance(a, Tag) and ("pIndex" in a["href"] or "seq=3" in a["href"])
        ]
        if not anchors:
            raise AddressNotFound(f"No properties for {address.house_number}, {address.postcode}")
        anchor = anchors[0] if cfg.match == "first" else match_address(address, anchors, text=text_of)

        r = await http.get(urljoin(r.url, str(anchor["href"])))
        page = soup(r.text)
        if page.find("span", id="waste-hint"):
            raise AddressNotFound(f"Whitespace has no schedule for {address.house_number}, {address.postcode}")
        section = page.find("section", id="scheduled-collections")
        if not isinstance(section, Tag):
            raise UpstreamError("Whitespace property page has no scheduled-collections section")

        collections = []
        # The portal's markup has both <ul> and (typo'd) <u1> containers.
        for box in section.find_all(["ul", "u1", "ol"]):
            items = box.find_all("li", recursive=False)
            if len(items) < 3:
                continue
            try:
                day = datetime.strptime(items[1].get_text(strip=True), cfg.date_format).date()
            except ValueError:
                continue
            name = items[2].get_text(strip=True)
            for suffix in cfg.strip_suffixes:
                name = name.removesuffix(suffix)
            name = name.strip()
            if cfg.upper:
                name = name.upper()
            if cfg.only_renamed and name not in cfg.rename:
                continue
            collections.append(Collection(day, cfg.rename.get(name, name)))
        return collections
