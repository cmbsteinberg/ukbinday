#!/usr/bin/env python3
"""
Patch and integrate RobBrad scrapers into the API.

Reads input.json from the cloned RobBrad repo, filters out scrapers that
are already covered by Mampfes or use Selenium, rewrites imports to use
our local shims, converts requests → httpx (sync), and appends a Source
adapter class that bridges to the project API.
"""

import ast
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline.shared import (
    BLOCKED_DOMAINS,
    extract_gov_uk_prefix,
    load_admin_lookup,
    load_overrides,
    normalise_domain,
    save_admin_lookup,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def is_selenium_scraper(file_path: Path) -> bool:
    """Check if a scraper file uses selenium."""
    content = file_path.read_text().lower()
    return "selenium" in content or "webdriver" in content


def get_class_name(tree: ast.AST) -> str | None:
    """Find the scraper class (AbstractGetBinDataClass subclass) in the AST.

    Prefers CouncilClass or any class inheriting from AbstractGetBinDataClass.
    Falls back to the first class if no subclass is found.
    """
    first_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if first_class is None:
                first_class = node.name
            for base in node.bases:
                base_name = None
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name == "AbstractGetBinDataClass":
                    return node.name
    return first_class


def rewrite_imports(source: str) -> str:
    """Rewrite uk_bin_collection imports to our local shim."""
    source = re.sub(
        r"from\s+uk_bin_collection\.uk_bin_collection\.common\s+import\s+",
        "from api.compat.ukbcd.common import ",
        source,
    )
    source = re.sub(
        r"from\s+uk_bin_collection\.uk_bin_collection\.get_bin_data\s+import\s+",
        "from api.compat.ukbcd.get_bin_data import ",
        source,
    )
    source = re.sub(
        r"from\s+uk_bin_collection\.uk_bin_collection\.",
        "from api.compat.ukbcd.",
        source,
    )
    return source


def _replace_requests_imports(source: str) -> str:
    """Replace import statements for requests → httpx."""
    source = re.sub(r"^import requests\s*$", "import httpx", source, flags=re.MULTILINE)
    source = re.sub(
        r"^from\s+requests\b.*$", "import httpx", source, flags=re.MULTILINE
    )
    return source


def _replace_requests_api_calls(source: str) -> str:
    """Replace requests.get/post/etc and Session() with httpx equivalents."""
    source = re.sub(
        r"\brequests\.(get|post|put|delete|patch|head|request)\b", r"httpx.\1", source
    )
    source = source.replace("requests.Session()", "httpx.Client(follow_redirects=True)")
    source = source.replace("requests.session()", "httpx.Client(follow_redirects=True)")
    source = source.replace("requests.Response", "httpx.Response")
    return source


def _replace_requests_exceptions(source: str) -> str:
    """Replace requests.exceptions.* with httpx equivalents."""
    source = source.replace("requests.exceptions.RequestException", "httpx.HTTPError")
    source = source.replace("requests.exceptions.HTTPError", "httpx.HTTPStatusError")
    source = source.replace("requests.HTTPError", "httpx.HTTPStatusError")
    source = source.replace("requests.RequestException", "httpx.HTTPError")
    return source


def _strip_urllib3_references(source: str) -> str:
    """Remove requests.packages.urllib3.* references."""
    source = re.sub(
        r"requests\.packages\.urllib3\.disable_warnings\([^)]*\)",
        "pass  # urllib3 warnings disabled",
        source,
    )
    source = re.sub(
        r"^[^\n]*requests\.packages\.urllib3\.[^\n]*\n?",
        "",
        source,
        flags=re.MULTILINE,
    )
    return source


def _strip_requests_adapters(source: str) -> str:
    """Strip HTTPAdapter imports, Retry imports, and .mount() calls."""
    source = re.sub(
        r"^from\s+requests\.structures\s+import\s+CaseInsensitiveDict\n?",
        "",
        source,
        flags=re.MULTILINE,
    )
    source = source.replace("CaseInsensitiveDict()", "{}")
    source = re.sub(
        r"^from\s+requests\.adapters\s+import\s+HTTPAdapter\n?",
        "",
        source,
        flags=re.MULTILINE,
    )
    source = re.sub(
        r"^from\s+urllib3\.util\.retry\s+import\s+Retry\n?",
        "",
        source,
        flags=re.MULTILINE,
    )
    source = re.sub(
        r"^[ \t]+\w+\s*=\s*Retry\([^)]*\)\n?",
        "",
        source,
        flags=re.MULTILINE,
    )
    source = re.sub(r"^[ \t]+\w+\.mount\([^)]*\)\n?", "", source, flags=re.MULTILINE)
    return source


def _fix_httpx_compat(source: str) -> str:
    """Fix httpx-specific incompatibilities (allow_redirects, .ok, cookies, etc)."""
    source = source.replace("allow_redirects=", "follow_redirects=")
    source = re.sub(r"(\w+)\.ok\b", r"\1.is_success", source)
    source = re.sub(r"(\w+)\.cookies:", r"\1.cookies.jar:", source)
    source = re.sub(r"in (\w+)\.cookies\b(?!\.)", r"in \1.cookies.jar", source)
    # Convert positional data arg in .post()/.put()/.patch() to keyword arg
    source = re.sub(
        r"(\.\s*(?:post|put|patch)\([^,\n]+),\s+(?!data=|json=|files=|headers=|params=|timeout=|content=|cookies=|auth=|follow_redirects=|verify=)(\w+)\)",
        r"\1, data=\2)",
        source,
    )
    return source


def _hoist_verify_false(source: str) -> str:
    """Move verify=False from per-request calls to Client constructor."""
    has_verify_in_calls = bool(
        re.search(r"\.(get|post|put|delete|patch|head)\([^)]*verify=", source)
    )
    if not has_verify_in_calls:
        return source

    lines = source.split("\n")
    new_lines = []
    for line in lines:
        if "verify=False" in line and "Client(" not in line:
            line = re.sub(r",\s*verify=False", "", line)
            line = re.sub(r"verify=False,\s*", "", line)
        new_lines.append(line)
    source = "\n".join(new_lines)
    source = source.replace(
        "httpx.Client(follow_redirects=True)",
        "httpx.Client(verify=False, follow_redirects=True)",
    )
    return source


def _ensure_httpx_import(source: str) -> str:
    """Ensure import httpx is present if httpx is referenced."""
    if "httpx." not in source or "import httpx" in source:
        return source
    lines = source.split("\n")
    last_import_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) and not line.startswith(
            (" ", "\t")
        ):
            last_import_idx = i
    lines.insert(last_import_idx + 1, "import httpx")
    return "\n".join(lines)


def convert_requests_to_httpx_sync(source: str) -> str:
    """Convert requests usage to httpx (sync Client, not AsyncClient)."""
    source = _replace_requests_imports(source)
    source = _replace_requests_api_calls(source)
    source = _replace_requests_exceptions(source)
    source = _strip_urllib3_references(source)
    source = _strip_requests_adapters(source)
    source = _fix_httpx_compat(source)
    source = _hoist_verify_false(source)
    source = _ensure_httpx_import(source)
    return source


def detect_init_params(data: dict) -> list[str]:
    """Detect which params this scraper needs from input.json test data."""
    params = []
    if "uprn" in data:
        params.append("uprn")
    if "postcode" in data:
        params.append("postcode")
    if "paon" in data or "house_number" in data:
        params.append("house_number")
    if "usrn" in data:
        params.append("usrn")
    if not params:
        params.append("uprn")
    return params


def generate_adapter_code(
    original_class_name: str, params: list[str], url: str, title: str
) -> str:
    """Generate the Source adapter class."""
    init_args = ", ".join([f"{p}: str | None = None" for p in params])
    init_body = "\n".join([f"        self.{p} = {p}" for p in params])

    kwargs_lines = []
    for p in params:
        ukbcd_key = "paon" if p == "house_number" else p
        kwargs_lines.append(f"        if self.{p}: kwargs['{ukbcd_key}'] = self.{p}")
    kwargs_block = "\n".join(kwargs_lines)

    return f'''

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "{title}"
URL = "{url}"
TEST_CASES = {{}}


class Source:
    def __init__(self, {init_args}):
{init_body}
        self._scraper = {original_class_name}()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        kwargs = {{}}
{kwargs_block}

        def _run():
            page = ""
            if hasattr(self._scraper, "parse_data"):
                return self._scraper.parse_data(page, **kwargs)
            raise NotImplementedError("Could not find parse_data on scraper")

        data = await asyncio.to_thread(_run)

        entries = []
        if isinstance(data, dict) and "bins" in data:
            for item in data["bins"]:
                bin_type = item.get("type")
                date_str = item.get("collectionDate")
                if not bin_type or not date_str:
                    continue
                try:
                    if "-" in date_str:
                        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                    elif "/" in date_str:
                        dt = datetime.strptime(date_str, "%d/%m/%Y").date()
                    else:
                        continue
                    entries.append(Collection(date=dt, t=bin_type, icon=None))
                except ValueError:
                    continue
        return entries
'''


def _load_ukbcd_override_domains() -> set[str]:
    """Load domains where UKBCD should be preferred over HACS."""
    overrides = load_overrides()
    domains = set(overrides.get("hacs_to_ukbcd", {}).keys())
    if domains:
        logger.info(f"Loaded {len(domains)} HACS→UKBCD overrides.")
    return domains


def _resolve_url(data: dict) -> str | None:
    """Extract the URL from a council's input.json data."""
    return data.get("url") or data.get("wiki_url")


def _process_council(
    council_name: str,
    data: dict,
    councils_dir: Path,
    target_dir: Path,
) -> str | None:
    """Process a single council scraper. Returns the sanitized filename on success, None on skip."""
    source_file = councils_dir / f"{council_name}.py"
    if not source_file.exists():
        logger.warning(f"Source file not found for {council_name}")
        return None

    if is_selenium_scraper(source_file):
        return None

    source_code = source_file.read_text()
    new_source = rewrite_imports(source_code)
    new_source = convert_requests_to_httpx_sync(new_source)

    try:
        tree = ast.parse(new_source)
        class_name = get_class_name(tree)
    except SyntaxError:
        class_name = None

    if not class_name:
        logger.warning(f"Could not find class in {council_name}, skipping.")
        return None

    params = detect_init_params(data)

    title = data.get("wiki_name", "")
    if not title:
        title = re.sub(r"(?<!^)(?=[A-Z])", " ", council_name)

    url = _resolve_url(data) or ""
    adapter = generate_adapter_code(class_name, params, url, title)
    final_source = new_source + adapter

    sanitized_name = "ukbcd_" + re.sub(r"(?<!^)(?=[A-Z])", "_", council_name).lower()
    target_file = target_dir / f"{sanitized_name}.py"
    target_file.write_text(final_source)
    return sanitized_name


@dataclass
class _PatchStats:
    added: int = 0
    skipped_selenium: int = 0
    skipped_existing: int = 0
    skipped_blocked: int = 0

    def log_summary(self) -> None:
        logger.info("Summary:")
        logger.info(f"  Added: {self.added}")
        logger.info(f"  Skipped (Existing/Mampfes): {self.skipped_existing}")
        logger.info(f"  Skipped (Selenium): {self.skipped_selenium}")
        logger.info(f"  Skipped (Blocked domain): {self.skipped_blocked}")


def _should_skip_council(
    data: dict,
    non_ukbcd_lookup: dict[str, str],
    hacs_prefixes: set[str],
    ukbcd_override_domains: set[str],
    stats: _PatchStats,
) -> tuple[bool, str | None]:
    """Check if a council should be skipped. Returns (skip, domain)."""
    url = _resolve_url(data)
    if not url:
        return True, None

    domain = normalise_domain(url)

    if domain in BLOCKED_DOMAINS:
        stats.skipped_blocked += 1
        return True, domain

    # Check by full domain first, then by gov.uk prefix
    has_hacs = domain in non_ukbcd_lookup
    if not has_hacs:
        prefix = extract_gov_uk_prefix(url)
        if prefix and prefix in hacs_prefixes:
            has_hacs = True

    if has_hacs and domain not in ukbcd_override_domains:
        stats.skipped_existing += 1
        return True, domain

    return False, domain


def _patch_councils(
    input_data: dict,
    councils_dir: Path,
    target_dir: Path,
    non_ukbcd_lookup: dict[str, str],
    hacs_prefixes: set[str],
    ukbcd_override_domains: set[str],
) -> tuple[dict[str, str], _PatchStats]:
    """Process all councils from input.json. Returns (new_ukbcd_lookup, stats)."""
    new_ukbcd_lookup: dict[str, str] = {}
    stats = _PatchStats()

    for council_name, data in input_data.items():
        if not isinstance(data, dict):
            continue

        skip, domain = _should_skip_council(
            data, non_ukbcd_lookup, hacs_prefixes, ukbcd_override_domains, stats
        )
        if skip:
            continue

        logger.info(f"Adding new scraper: {council_name} ({domain})")
        sanitized_name = _process_council(council_name, data, councils_dir, target_dir)

        if sanitized_name is None:
            source_file = councils_dir / f"{council_name}.py"
            if source_file.exists() and is_selenium_scraper(source_file):
                stats.skipped_selenium += 1
            continue

        stats.added += 1
        new_ukbcd_lookup[domain] = sanitized_name

    return new_ukbcd_lookup, stats


def _load_input_data(clone_dir: Path) -> dict:
    """Load and validate input.json from the clone directory."""
    input_json_path = clone_dir / "uk_bin_collection" / "tests" / "input.json"
    if not input_json_path.exists():
        logger.error(f"Input JSON not found: {input_json_path}")
        sys.exit(1)
    try:
        return json.loads(input_json_path.read_text())
    except json.JSONDecodeError:
        logger.error("Failed to parse input.json")
        sys.exit(1)


def main():
    if len(sys.argv) < 3:
        print("Usage: python patch_scrapers.py <CLONE_DIR> <SCRAPERS_DIR>")
        sys.exit(1)

    clone_dir = Path(sys.argv[1])
    target_dir = Path(sys.argv[2])
    councils_dir = clone_dir / "uk_bin_collection" / "uk_bin_collection" / "councils"

    input_data = _load_input_data(clone_dir)

    admin_lookup = load_admin_lookup()
    non_ukbcd_lookup = {
        k: v for k, v in admin_lookup.items() if not v.startswith("ukbcd_")
    }
    ukbcd_override_domains = _load_ukbcd_override_domains()

    # Build gov.uk prefix set from HACS scrapers on disk for fuzzy matching
    hacs_prefixes = set()
    for p in sorted(target_dir.glob("hacs_*.py")):
        stem = p.stem.removeprefix("hacs_")
        if "_gov_uk" in stem:
            hacs_prefixes.add(stem.rsplit("_gov_uk", 1)[0].replace("_", "-"))

    logger.info(
        f"Loaded {len(non_ukbcd_lookup)} existing non-ukbcd councils from lookup "
        f"({len(hacs_prefixes)} gov.uk prefixes)."
    )

    new_ukbcd_lookup, stats = _patch_councils(
        input_data,
        councils_dir,
        target_dir,
        non_ukbcd_lookup,
        hacs_prefixes,
        ukbcd_override_domains,
    )

    if stats.added > 0:
        merged_lookup = {**non_ukbcd_lookup, **new_ukbcd_lookup}
        logger.info(
            f"Updating admin_scraper_lookup.json with {stats.added} new ukbcd entries..."
        )
        save_admin_lookup(merged_lookup)

    stats.log_summary()


if __name__ == "__main__":
    main()
