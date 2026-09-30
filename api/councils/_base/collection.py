"""The scraper's output: one bin on one day."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Icon(StrEnum):
    """Material Design icon names, the same strings the hacs scrapers used, so
    cached calendars keep their existing event descriptions."""

    GENERAL_WASTE = "mdi:trash-can"
    RECYCLING = "mdi:recycle"
    PAPER = "mdi:package-variant"
    GLASS = "mdi:bottle-soda"
    PLASTIC = "mdi:recycle-variant"
    METAL = "mdi:nail"
    FOOD = "mdi:food-apple"
    GARDEN = "mdi:flower"
    ORGANIC = "mdi:leaf"
    TEXTILE = "mdi:hanger"
    BATTERY = "mdi:battery"
    ELECTRONICS = "mdi:desktop-classic"
    BULKY = "mdi:sofa"
    CHRISTMAS_TREE = "mdi:pine-tree"
    COMMERCIAL = "mdi:factory"


@dataclass(frozen=True, slots=True)
class Collection:
    date: date
    type: str
    """The council's own name for the bin or service, e.g. "Recycling (Blue Bin)"."""
    icon: str | None = None
    """Leave unset unless the council's naming defeats `default_icon`; the
    harness fills it from `Scraper.icons`, then `default_icon`."""


# First match wins, so the specific streams come before the catch-alls:
# "Garden and food waste" is garden, "Food waste" is food, "Glass recycling" is glass.
_ICON_RULES: tuple[tuple[re.Pattern[str], Icon], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), icon)
    for pattern, icon in (
        (r"christmas|xmas|\btree", Icon.CHRISTMAS_TREE),
        (r"garden|green waste|brown bin", Icon.GARDEN),
        (r"food|caddy|kitchen", Icon.FOOD),
        (r"mixed", Icon.RECYCLING),
        (r"glass|bottle", Icon.GLASS),
        (r"paper|card|fibre", Icon.PAPER),
        (r"plastic|\bcans?\b|tins?\b|container", Icon.PLASTIC),
        (r"textile|cloth", Icon.TEXTILE),
        (r"batter", Icon.BATTERY),
        (r"electric|weee", Icon.ELECTRONICS),
        (r"bulky", Icon.BULKY),
        (r"trade|commercial", Icon.COMMERCIAL),
        (r"recycl", Icon.RECYCLING),
        (r"refuse|rubbish|general|residual|domestic|landfill|household", Icon.GENERAL_WASTE),
    )
)


def default_icon(bin_type: str) -> Icon | None:
    """Guess an icon from common words in the council's bin name."""
    # "Non-recyclable" must not hit the recycling rule first.
    if re.search(r"non.?recycl", bin_type, re.IGNORECASE):
        return Icon.GENERAL_WASTE
    for pattern, icon in _ICON_RULES:
        if pattern.search(bin_type):
            return icon
    return None
