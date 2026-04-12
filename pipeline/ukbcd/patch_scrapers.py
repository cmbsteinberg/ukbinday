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
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.shared import (
    BLOCKED_DOMAINS,
    LAD_LOOKUP_PATH,
    extract_gov_uk_prefix,
    load_overrides,
    normalise_domain,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def is_selenium_scraper(file_path: Path) -> bool:
    """Check if a scraper file actually uses selenium (not just imports it).

    Uses ruff F401 to detect unused selenium/webdriver imports. If every
    selenium-related import is flagged unused, the scraper doesn't truly
    depend on selenium and can be processed as a normal requests scraper.
    """
    import subprocess

    content = file_path.read_text()
    if "selenium" not in content.lower() and "webdriver" not in content.lower():
        return False

    # Count lines that are selenium/webdriver imports
    selenium_import_lines = [
        i + 1
        for i, line in enumerate(content.splitlines())
        if re.match(r"^\s*(?:from|import)\s+", line)
        and ("selenium" in line.lower() or "webdriver" in line.lower())
    ]
    if not selenium_import_lines:
        # Mentioned only in comments/docstrings, not imported
        return False

    try:
        result = subprocess.run(
            ["ruff", "check", "--select=F401", "--output-format=text", str(file_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # ruff output lines look like: "path.py:3:1: F401 `selenium.webdriver` imported but unused"
        unused_line_nums = set()
        for line in result.stdout.splitlines():
            if "selenium" in line.lower() or "webdriver" in line.lower():
                parts = line.split(":")
                if len(parts) >= 2 and parts[1].strip().isdigit():
                    unused_line_nums.add(int(parts[1].strip()))

        if unused_line_nums and set(selenium_import_lines) <= unused_line_nums:
            logger.info(f"Selenium imports unused in {file_path.name}, treating as non-selenium")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # ruff not available, fall through to conservative check

    return True


def _process_selenium_council(
    council_name: str,
    data: dict,
    source_file: Path,
    target_dir: Path,
) -> str | None:
    """Transpile a Selenium scraper to async Playwright. Returns sanitized filename or None."""
    from pipeline.ukbcd.patch_selenium_scrapers import transpile

    source_code = source_file.read_text()

    # Get class name from original source
    try:
        tree = ast.parse(source_code)
        class_name = get_class_name(tree)
    except SyntaxError:
        class_name = None

    if not class_name:
        logger.warning(f"Could not find class in {council_name} (Selenium), skipping.")
        return None

    # Rewrite UKBCD imports, convert any requests usage to httpx
    source_code = rewrite_imports(source_code)
    source_code = convert_requests_to_httpx_sync(source_code)

    # Transpile Selenium → async Playwright
    try:
        transpiled = transpile(source_code)
    except Exception as e:
        logger.warning(f"Transpilation failed for {council_name}: {e}")
        return None

    # Generate adapter
    params = detect_init_params(data)
    title = data.get("wiki_name", "")
    if not title:
        title = re.sub(r"(?<!^)(?=[A-Z])", " ", council_name)
    url = _resolve_url(data) or ""
    adapter = generate_playwright_adapter_code(class_name, params, url, title)

    final_source = transpiled + adapter
    sanitized_name = "ukbcd_" + re.sub(r"(?<!^)(?=[A-Z])", "_", council_name).lower()
    target_file = target_dir / f"{sanitized_name}.py"
    target_file.write_text(final_source)

    logger.info(f"Transpiled Selenium → Playwright: {council_name}")
    return sanitized_name


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


def generate_playwright_adapter_code(
    original_class_name: str, params: list[str], url: str, title: str
) -> str:
    """Generate the Source adapter class for async Playwright scrapers."""
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
        from datetime import datetime

        kwargs = {{}}
{kwargs_block}

        data = await self._scraper.parse_data("", **kwargs)

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


def generate_adapter_code(
    original_class_name: str, params: list[str], url: str, title: str
) -> str:
    """Generate the Source adapter class for requests-based scrapers."""
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
        # Selenium→Playwright transpilation disabled; skip selenium scrapers
        # return _process_selenium_council(council_name, data, source_file, target_dir)
        logger.info(f"Skipping Selenium scraper: {council_name}")
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
    added_playwright: int = 0
    skipped_selenium: int = 0
    skipped_existing: int = 0
    lad_mappings: dict = field(default_factory=dict)

    def log_summary(self) -> None:
        logger.info("Summary:")
        logger.info(f"  Added (requests): {self.added}")
        logger.info(f"  Added (Playwright): {self.added_playwright}")
        logger.info(f"  Skipped (Existing/Mampfes): {self.skipped_existing}")
        logger.info(f"  Skipped (Selenium failures): {self.skipped_selenium}")
        logger.info(f"  LAD mappings: {len(self.lad_mappings)}")


def _council_to_ukbcd_name(council_name: str) -> str:
    """Compute the UKBCD scraper filename from a council name (deterministic)."""
    return "ukbcd_" + re.sub(r"(?<!^)(?=[A-Z])", "_", council_name).lower()


def _get_lad_codes(data: dict) -> list[str]:
    """Extract LAD codes from a council's input.json data."""
    lad_codes = []
    if "LAD24CD" in data:
        lad_codes.append(data["LAD24CD"])
    if "supported_councils_LAD24CD" in data:
        lad_codes.extend(data["supported_councils_LAD24CD"])
    return lad_codes


def _find_hacs_scraper(
    url: str,
    hacs_domain_lookup: dict[str, str],
    hacs_prefixes: set[str],
) -> str | None:
    """Try to find a HACS scraper matching this URL (domain then prefix fallback)."""
    domain = normalise_domain(url)
    scraper = hacs_domain_lookup.get(domain)
    if scraper:
        return scraper
    prefix = extract_gov_uk_prefix(url)
    if prefix and prefix in hacs_prefixes:
        for d, name in hacs_domain_lookup.items():
            if extract_gov_uk_prefix("https://" + d) == prefix:
                return name
    return None


def _patch_councils(
    input_data: dict,
    councils_dir: Path,
    target_dir: Path,
    hacs_domain_lookup: dict[str, str],
    hacs_prefixes: set[str],
    ukbcd_override_domains: set[str],
) -> _PatchStats:
    """Process all councils from input.json. Returns stats (including lad_mappings).

    Two-phase approach:
      Phase 1: Record every council's LAD codes with its UKBCD scraper name as
               the default (deterministic from council_name, never fails).
               Also create UKBCD scrapers for councils not covered by HACS.
      Phase 2: Upgrade UKBCD scraper_ids to HACS where a match exists, and
               validate that every recorded scraper_id actually exists on disk.
    """
    stats = _PatchStats()

    # Phase 1: Process councils and record baseline LAD mappings
    for council_name, data in input_data.items():
        if not isinstance(data, dict):
            continue

        url = _resolve_url(data)
        if not url:
            continue

        domain = normalise_domain(url)

        ukbcd_name = _council_to_ukbcd_name(council_name)
        lad_codes = _get_lad_codes(data)
        name = data.get("wiki_name") or ""

        # Record baseline: every council gets its UKBCD scraper name
        for lad in lad_codes:
            if lad not in stats.lad_mappings:
                stats.lad_mappings[lad] = {
                    "name": name,
                    "scraper_id": ukbcd_name,
                    "url": url,
                }

        # Blocked domains (e.g. calendar.google.com) can't be matched to
        # HACS scrapers by domain, but should still be synced as UKBCD scrapers
        if domain not in BLOCKED_DOMAINS:
            hacs_scraper = _find_hacs_scraper(url, hacs_domain_lookup, hacs_prefixes)
        else:
            hacs_scraper = None

        if hacs_scraper and domain not in ukbcd_override_domains:
            stats.skipped_existing += 1
            # Upgrade to HACS scraper_id
            for lad in lad_codes:
                stats.lad_mappings[lad]["scraper_id"] = hacs_scraper
            continue

        # No HACS match -- create UKBCD scraper
        source_file = councils_dir / f"{council_name}.py"
        is_selenium = source_file.exists() and is_selenium_scraper(source_file)

        logger.info(f"Adding new scraper: {council_name} ({domain})")
        sanitized_name = _process_council(council_name, data, councils_dir, target_dir)

        if sanitized_name is None:
            if is_selenium:
                stats.skipped_selenium += 1
            continue

        if is_selenium:
            stats.added_playwright += 1
        else:
            stats.added += 1
        # Update with actual sanitized name (should match ukbcd_name, but use
        # the real value from _process_council to be safe)
        for lad in lad_codes:
            stats.lad_mappings[lad]["scraper_id"] = sanitized_name

    # Phase 2: Validate that every recorded scraper_id exists on disk
    for lad, entry in stats.lad_mappings.items():
        sid = entry["scraper_id"]
        if sid and not (target_dir / f"{sid}.py").exists():
            entry["scraper_id"] = None

    return stats


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

    # Build domain -> scraper mapping from hacs files on disk
    from pipeline.shared import build_hacs_domain_lookup

    hacs_domain_lookup = build_hacs_domain_lookup(target_dir)
    ukbcd_override_domains = _load_ukbcd_override_domains()

    # Build gov.uk prefix set from HACS scrapers on disk for fuzzy matching
    hacs_prefixes = set()
    for p in sorted(target_dir.glob("hacs_*.py")):
        stem = p.stem.removeprefix("hacs_")
        if "_gov_uk" in stem:
            hacs_prefixes.add(stem.rsplit("_gov_uk", 1)[0].replace("_", "-"))

    logger.info(
        f"Found {len(hacs_domain_lookup)} hacs scrapers on disk "
        f"({len(hacs_prefixes)} gov.uk prefixes)."
    )

    stats = _patch_councils(
        input_data,
        councils_dir,
        target_dir,
        hacs_domain_lookup,
        hacs_prefixes,
        ukbcd_override_domains,
    )

    # Write lad_lookup.json directly
    if stats.lad_mappings:
        logger.info(
            f"Writing {len(stats.lad_mappings)} LAD mappings to lad_lookup.json"
        )
        LAD_LOOKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAD_LOOKUP_PATH.write_text(json.dumps(stats.lad_mappings, indent=2))

    stats.log_summary()


if __name__ == "__main__":
    main()
