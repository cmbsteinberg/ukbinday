"""Find the council modules, check which LADs they claim, and read the ID aliases."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from api.councils._base.scraper import Scraper

COUNCILS_DIR = Path(__file__).resolve().parent.parent
LAD_LOOKUP = COUNCILS_DIR.parent / "data" / "lad_lookup.json"
ALIASES = COUNCILS_DIR / "_aliases.json"
"""Old scraper IDs (every one ever wired to a LAD, up to the switch to LAD codes)
and recoded LAD codes -> the current LAD code. Old calendar URLs (`council=`) and
ICS sidecars (`scraper`) carry them. Frozen: public IDs are LAD codes now, so a
new entry is needed only when ONS recodes a LAD."""


def aliases() -> dict[str, str]:
    return json.loads(ALIASES.read_text())


def module_names() -> list[str]:
    return sorted(p.stem for p in COUNCILS_DIR.glob("*.py") if not p.stem.startswith("_"))


def load(name: str) -> Scraper:
    module = importlib.import_module(f"api.councils.{name}")
    scraper = getattr(module, "SCRAPER", None)
    if not isinstance(scraper, Scraper):
        raise TypeError(f"api.councils.{name} has no SCRAPER instance")
    return scraper


def by_lad(scrapers: dict[str, Scraper]) -> dict[str, str]:
    """LAD code -> module name. Raises on a code claimed twice or not a real LAD."""
    known = set(json.loads(LAD_LOOKUP.read_text()))
    owner: dict[str, str] = {}
    for name, scraper in scrapers.items():
        for lad in scraper.meta.lads:
            if lad not in known:
                raise ValueError(f"{name} claims {lad}, which isn't a LAD postcodes resolve to")
            if lad in owner:
                raise ValueError(f"{lad} is claimed by both {owner[lad]} and {name}")
            owner[lad] = name
    return owner
