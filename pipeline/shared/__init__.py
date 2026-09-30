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
# LAD code -> {scraper_id, url}, this sync's scraper wiring. Composed with
# pipeline/data/lad_base.json (ONS/GOV.UK ground truth) into LAD_LOOKUP_PATH by
# scripts/lookup/build_lad_lookup.py.
SCRAPER_LAD_MAP_PATH = PIPELINE_DIR / "data" / "scraper_lad_map.json"
ROUTING_PATH = PIPELINE_DIR / "routing.json"
HACS_PATCH_OVERRIDES_PATH = PIPELINE_DIR / "hacs" / "patch_overrides.json"
LAD_OVERRIDES_PATH = PIPELINE_DIR / "lad_overrides.json"

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
    significant_words = [w for w in words if w not in _COUNCIL_FILLER]
    # Some proper names consist entirely of otherwise-generic filler words
    # (notably "City of London"). Never collapse a non-empty name to the
    # empty identifier, which would make unrelated councils collide.
    return "".join(significant_words or words)


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


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def load_routing() -> dict:
    """Load HACS↔UKBCD routing config (hacs_to_ukbcd map)."""
    return _load_json(ROUTING_PATH)


def load_hacs_patch_overrides() -> dict:
    """Load HACS AST-patcher knobs (fallbacks, ssl, broken, uprn aliases)."""
    return _load_json(HACS_PATCH_OVERRIDES_PATH)


def load_lad_overrides() -> dict:
    """Load preserved scrapers + LAD code overrides for sync orchestration."""
    return _load_json(LAD_OVERRIDES_PATH)


def load_unwired_lads() -> dict[str, str]:
    """LAD code -> reason for councils deliberately left without a scraper.

    Used to settle councils whose only upstream option is a placeholder that
    can never return real data (e.g. the shared UKBCD Google-calendar test
    fixture). Blocklisted codes are stripped from the scraper map at compose
    time so re-syncs can't silently re-wire them; the reason is recorded in
    lad_lookup.json as the entry's "status".
    """
    return load_lad_overrides().get("unwired_lads", {})


def load_deeplink_urls() -> dict[str, str]:
    """LAD code -> council bin page to deeplink to, overriding the composed url.

    Unwired LADs deeplink to their GOV.UK `govuk_url` by default, which is
    sometimes dead (Fylde's `/refuse` 404s after a portal redesign). An entry
    here replaces the entry's "url" at compose time, so api/services/deeplinks
    prefers it over GOV.UK. Only add a code whose default target is wrong.
    """
    return load_lad_overrides().get("deeplink_urls", {})
