"""Shared async client for Whitespace WRP ("Waste & Recycling Portal") sites.

Every `*-wrp.whitespacews.com` portal runs the same four-step flow:

1. GET the landing page and pick the "View my collections" link (``seq=1``,
   ``serviceID=A``), which carries a per-session ``Track=`` token.
2. POST the address form to the same link with ``seq=2``.
3. Pick a property from the results list (``#property_list``).
4. GET the property page and read ``section#scheduled-collections``, where each
   ``<ul>`` holds ``[icon, date, service name]`` list items.

What differs per council is data, captured in `WhitespaceConfig`: the base URL,
how to choose a property from the list, and how to tidy the service names.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs import Collection  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import SourceArgumentNotFound

_LOGGER = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

# Property-selection strategies (WhitespaceConfig.match)
MATCH_FIRST = "first"  # first listed property (postcode + number narrow it to one)
MATCH_CONTAINS = "contains"  # number appears in the link text (case-insensitive)
MATCH_NUMBER_STREET = "number_street"  # number and street both appear in link text
MATCH_PREFIX = "prefix"  # link text / aria-label starts with "<number>,"


@dataclass(frozen=True)
class WhitespaceConfig:
    """Per-council data for a Whitespace WRP portal."""

    base_url: str
    match: str = MATCH_FIRST
    # Service-name tidying, applied in this order.
    type_replace: tuple[tuple[str, str], ...] = ()  # (old, new) substring swaps
    strip_suffixes: tuple[str, ...] = ()
    upper: bool = False
    # Optional raw-name -> (title, icon). With drop_unmapped, other services are skipped.
    type_map: dict[str, tuple[str, str]] = field(default_factory=dict)
    drop_unmapped: bool = False
    # Icons keyed by tidied name; None entries fall back to default_icon.
    icon_map: dict[str, str] = field(default_factory=dict)
    default_icon: str | None = None
    date_format: str = "%d/%m/%Y"
    timeout: float = 45.0


def normalise_postcode(postcode: str) -> str:
    """Upper-case and ensure the single space the portal's search expects."""
    pc = re.sub(r"\s+", "", postcode or "").upper()
    return f"{pc[:-3]} {pc[-3:]}" if len(pc) > 3 else pc


def _landing_link(soup: BeautifulSoup) -> str:
    links = [a for a in soup.find_all("a", href=True) if "seq=1" in a["href"]]
    if not links:
        raise ValueError("Whitespace landing page has no collections link")
    for a in links:
        if a.get_text(strip=True).lower() == "view my collections":
            return a["href"]
    for a in links:
        if "serviceID=A" in a["href"]:
            return a["href"]
    return links[0]["href"]


def _pick_property(soup: BeautifulSoup, cfg: WhitespaceConfig, number, street):
    container = soup.find(id="property_list") or soup
    anchors = container.find_all("a", href=True)
    anchors = [a for a in anchors if "pIndex" in a["href"] or "seq=3" in a["href"]]
    if not anchors:
        return None
    if cfg.match == MATCH_FIRST:
        return anchors[0]

    num = str(number or "").strip().lower()
    st = (street or "").strip().lower()
    for a in anchors:
        text = a.get_text(strip=True).lower()
        label = a.get("aria-label", "").lower()
        if cfg.match == MATCH_CONTAINS and num in text:
            return a
        if cfg.match == MATCH_NUMBER_STREET and num in text and st in text:
            return a
        if cfg.match == MATCH_PREFIX and (
            label.startswith(num + ",") or text.startswith(num + ",")
        ):
            return a
    return None


def _tidy(raw: str, cfg: WhitespaceConfig) -> tuple[str, str | None] | None:
    if cfg.type_map:
        hit = cfg.type_map.get(raw)
        if hit:
            return hit
        if cfg.drop_unmapped:
            return None
    name = raw
    for old, new in cfg.type_replace:
        name = name.replace(old, new)
    for suffix in cfg.strip_suffixes:
        name = name.removesuffix(suffix)
    name = name.strip()
    if cfg.upper:
        name = name.upper()
    return name, cfg.icon_map.get(name, cfg.default_icon)


def _parse_schedule(html: str, cfg: WhitespaceConfig) -> list[Collection]:
    soup = BeautifulSoup(html, "html.parser")
    section = soup.find("section", id="scheduled-collections")
    if section is None:
        raise ValueError("Could not find scheduled-collections section on WRP page")

    entries: list[Collection] = []
    # The portal's markup contains both <ul> and (typo'd) <u1> containers.
    for box in section.find_all(["ul", "u1", "ol"]):
        lis = box.find_all("li", recursive=False)
        if len(lis) < 3:
            continue
        date_text = lis[1].get_text(strip=True)
        raw_type = lis[2].get_text(strip=True)
        try:
            date = datetime.strptime(date_text, cfg.date_format).date()
        except ValueError:
            _LOGGER.info("Skipped %r: not a %s date", date_text, cfg.date_format)
            continue
        tidy = _tidy(raw_type, cfg)
        if tidy is None:
            continue
        name, icon = tidy
        entries.append(Collection(date=date, t=name, icon=icon))
    entries.sort(key=lambda c: c.date)
    return entries


async def fetch_collections(
    cfg: WhitespaceConfig,
    *,
    number: str | int | None,
    postcode: str,
    street: str = "",
    town: str = "",
) -> list[Collection]:
    """Run the WRP flow for one address and return its collections."""
    postcode = normalise_postcode(postcode)
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=cfg.timeout, headers=_HEADERS
    ) as client:
        r = await client.get(cfg.base_url.rstrip("/") + "/")
        r.raise_for_status()
        link = _landing_link(BeautifulSoup(r.text, "html.parser"))

        r = await client.post(
            link.replace("seq=1", "seq=2"),
            data={
                "address_name_number": "" if number is None else str(number),
                "address_street": street or "",
                "street_town": town or "",
                "address_postcode": postcode,
            },
        )
        r.raise_for_status()
        anchor = _pick_property(
            BeautifulSoup(r.text, "html.parser"), cfg, number, street
        )
        if anchor is None:
            raise SourceArgumentNotFound("house_number", str(number))

        r = await client.get(urljoin(str(r.url), anchor["href"]))
        r.raise_for_status()
        if BeautifulSoup(r.text, "html.parser").find("span", id="waste-hint"):
            raise SourceArgumentNotFound("house_number", str(number))
        return _parse_schedule(r.text, cfg)
