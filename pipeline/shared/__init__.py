"""Shared utilities for the hacs and ukbcd pipeline scripts."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from urllib.parse import urlparse

# Paths
PIPELINE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PIPELINE_DIR.parent
API_DIR = PROJECT_ROOT / "api"
SCRAPERS_DIR = API_DIR / "scrapers"
LAD_LOOKUP_PATH = API_DIR / "data" / "lad_lookup.json"
OVERRIDES_PATH = PIPELINE_DIR / "overrides.json"

# Overly broad domains that should never be used as lookup keys
BLOCKED_DOMAINS = {
    "gov.uk",
    "calendar.google.com",
    "www.gov.uk",
}


# Common filler words to strip when normalising council names for matching
_COUNCIL_FILLER = {
    "council", "city", "borough", "district", "county", "metropolitan",
    "royal", "london", "of", "and", "the",
    "mb", "mbc", "mdc", "dc", "bc",  # abbreviations for Met. Borough etc.
}


def normalise_council_name(name: str) -> str:
    """Normalise a council name or scraper stem to a comparable key.

    Strips common filler words (council, city, borough, etc.), non-alpha chars,
    and domain suffixes so that e.g. 'BristolCityCouncil', 'bristol_gov_uk',
    and 'Bristol City Council' all normalise to 'bristol'.
    """
    import re as _re

    # Split CamelCase into words (handles sequences like "KnowsleyMBCouncil")
    name = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    name = _re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    name = name.lower()
    # Remove domain suffixes
    for suffix in ("_gov_uk", "_co_uk", "_org_uk", "_uk", ".gov.uk", ".co.uk", ".org.uk"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    # Replace non-alpha with space, split into words, strip filler
    words = _re.sub(r"[^a-z]+", " ", name).split()
    words = [w for w in words if w not in _COUNCIL_FILLER]
    return "".join(words)


def normalise_domain(url: str) -> str:
    """Extract bare domain from a URL."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def extract_gov_uk_prefix(url: str) -> str | None:
    """Extract the prefix before .gov.uk (or .gov.wales) from a URL.

    E.g. "https://online.aberdeenshire.gov.uk" -> "aberdeenshire"
         "https://www.allerdale.gov.uk" -> "allerdale"
         "https://anglesey.gov.wales" -> "anglesey"
         "https://apps.cloud9technologies.com" -> None (not gov.uk)
    """
    domain = normalise_domain(url)
    parts = domain.split(".")
    try:
        gov_idx = parts.index("gov")
    except ValueError:
        return None
    if gov_idx == 0:
        return None
    return parts[gov_idx - 1]


def extract_url_from_scraper(path: Path) -> str | None:
    """Parse the URL = '...' constant from a scraper file using AST."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "URL"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def build_hacs_domain_lookup(scrapers_dir: Path) -> dict[str, str]:
    """Build domain -> scraper name mapping from hacs scraper files on disk."""
    lookup: dict[str, str] = {}
    for path in sorted(scrapers_dir.glob("hacs_*.py")):
        url = extract_url_from_scraper(path)
        if not url:
            continue
        domain = normalise_domain(url)
        lookup[domain] = path.stem
    return lookup


def load_overrides() -> dict:
    """Load the pipeline overrides config."""
    if not OVERRIDES_PATH.exists():
        return {}
    return json.loads(OVERRIDES_PATH.read_text())
