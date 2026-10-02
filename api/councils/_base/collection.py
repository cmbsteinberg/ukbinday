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


_COLOURS = r"black|blue|brown|green|gr[ae]y|purple|red|white|yellow|orange|pink|burgundy|maroon"
_CONTAINER = (
    r"(?:wheel(?:ie|ed)[\s-]*)?"
    r"(?:bins?|box(?:es)?|caddy|caddies|sacks?|bags?|containers?|lid(?:ded)?|top|\d+\s?l)\b"
)

# First match wins. A colour only counts when it plausibly names the container:
# next to a container word ("Blue Bin", "red-lidded bin", "Bin BLUE 240"), in
# brackets ("Mixed Recycling (Blue)"), a litre size ("Empty 180L Blue"), trailing
# ("RECYCLING - BROWN") or leading the label ("Black refuse").
# "Green waste" / "green garden waste" is the stream, not a green bin, so it
# matches none of these.
_COLOUR_RULES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        rf"\b({_COLOURS})[\s-]*(?:(?:recycling|top(?:ped)?)[\s-]*)?{_CONTAINER}",
        rf"\bbin\s+({_COLOURS})\b",
        rf"\b({_COLOURS})\b(?:[\s-]+[a-z]+){{1,2}}[\s-]+{_CONTAINER}",
        rf"\(\s*({_COLOURS})\s*\)",
        rf"\b\d+\s?l\s+({_COLOURS})\b",
        rf"[-\u2013]\s*({_COLOURS})\s*$",
        # A leading colour names the bin, except a stream ("Green waste") or a
        # rota week ("Pink Week").
        rf"^\s*({_COLOURS})\b(?!\s+week\b)(?!(?<=green)\s+(?:waste|garden)\b)",
    )
)

_COLOUR_NAMES = {"gray": "Grey", "maroon": "Burgundy"}


def colour_of(label: str) -> str | None:
    """Pull a bin colour from the council's own label ("Recycling (Blue Bin)" -> "Blue").

    Returns None when the label names no colour, or only as part of a stream
    ("Green waste")."""
    for pattern in _COLOUR_RULES:
        if m := pattern.search(label):
            word = m.group(1).lower()
            return _COLOUR_NAMES.get(word, word.capitalize())
    return None
