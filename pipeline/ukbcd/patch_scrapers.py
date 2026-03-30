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
from pathlib import Path
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
API_DIR = PROJECT_ROOT / "api"
SCRAPERS_DIR = API_DIR / "scrapers"
ADMIN_LOOKUP_PATH = API_DIR / "data" / "admin_scraper_lookup.json"

# Overly broad domains that should never be used as lookup keys
BLOCKED_DOMAINS = {
    "gov.uk",
    "calendar.google.com",
    "www.gov.uk",
}


def normalise_domain(url: str) -> str:
    """Extract bare domain from a URL."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def load_admin_lookup() -> dict[str, str]:
    if not ADMIN_LOOKUP_PATH.exists():
        return {}
    return json.loads(ADMIN_LOOKUP_PATH.read_text())


def is_selenium_scraper(file_path: Path) -> bool:
    """Check if a scraper file uses selenium."""
    content = file_path.read_text().lower()
    return "selenium" in content or "webdriver" in content


def get_class_name(tree: ast.AST) -> str | None:
    """Find the first class definition in the AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            return node.name
    return None


def rewrite_imports(source: str) -> str:
    """Rewrite uk_bin_collection imports to our local shim."""
    # from uk_bin_collection.uk_bin_collection.common import *
    source = re.sub(
        r"from\s+uk_bin_collection\.uk_bin_collection\.common\s+import\s+",
        "from api.compat.ukbcd.common import ",
        source,
    )
    # from uk_bin_collection.uk_bin_collection.get_bin_data import ...
    source = re.sub(
        r"from\s+uk_bin_collection\.uk_bin_collection\.get_bin_data\s+import\s+",
        "from api.compat.ukbcd.get_bin_data import ",
        source,
    )
    # Any other uk_bin_collection imports
    source = re.sub(
        r"from\s+uk_bin_collection\.uk_bin_collection\.",
        "from api.compat.ukbcd.",
        source,
    )
    return source


def convert_requests_to_httpx_sync(source: str) -> str:
    """Convert requests usage to httpx (sync Client, not AsyncClient)."""
    # Replace import statements
    source = re.sub(r"^import requests\s*$", "import httpx", source, flags=re.MULTILINE)
    source = re.sub(
        r"^from\s+requests\b.*$", "import httpx", source, flags=re.MULTILINE
    )

    # requests.get/post/etc → httpx.get/post/etc
    source = re.sub(r"\brequests\.(get|post|put|delete|patch|head)\b", r"httpx.\1", source)

    # requests.Session() → httpx.Client(follow_redirects=True)
    source = source.replace("requests.Session()", "httpx.Client(follow_redirects=True)")
    source = source.replace("requests.session()", "httpx.Client(follow_redirects=True)")

    # requests.Response → httpx.Response
    source = source.replace("requests.Response", "httpx.Response")

    # requests.exceptions.X → httpx equivalents
    source = source.replace("requests.exceptions.RequestException", "httpx.HTTPError")
    source = source.replace("requests.exceptions.HTTPError", "httpx.HTTPStatusError")
    source = source.replace("requests.HTTPError", "httpx.HTTPStatusError")
    source = source.replace("requests.RequestException", "httpx.HTTPError")

    # requests.packages.urllib3.disable_warnings() → pass (no-op)
    source = re.sub(
        r"requests\.packages\.urllib3\.disable_warnings\([^)]*\)",
        "pass  # urllib3 warnings disabled",
        source,
    )

    # allow_redirects= → follow_redirects=
    source = source.replace("allow_redirects=", "follow_redirects=")

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
    # If no params detected, default to uprn (most common)
    if not params:
        params.append("uprn")
    return params


def generate_adapter_code(original_class_name: str, params: list[str], url: str, title: str) -> str:
    """Generate the Source adapter class."""

    # Build __init__ signature and body
    init_args = ", ".join([f"{p}: str | None = None" for p in params])
    init_body = "\n".join([f"        self.{p} = {p}" for p in params])

    # Map our param names to RobBrad's kwargs
    kwargs_lines = []
    for p in params:
        robbrad_key = "paon" if p == "house_number" else p
        kwargs_lines.append(f"        if self.{p}: kwargs['{robbrad_key}'] = self.{p}")
    kwargs_block = "\n".join(kwargs_lines)

    code = f'''

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
    return code


def main():
    if len(sys.argv) < 3:
        print("Usage: python patch_scrapers.py <CLONE_DIR> <SCRAPERS_DIR>")
        sys.exit(1)

    clone_dir = Path(sys.argv[1])
    target_dir = Path(sys.argv[2])

    input_json_path = clone_dir / "uk_bin_collection" / "tests" / "input.json"
    councils_dir = clone_dir / "uk_bin_collection" / "uk_bin_collection" / "councils"

    if not input_json_path.exists():
        logger.error(f"Input JSON not found: {input_json_path}")
        sys.exit(1)

    try:
        input_data = json.loads(input_json_path.read_text())
    except json.JSONDecodeError:
        logger.error("Failed to parse input.json")
        sys.exit(1)

    admin_lookup = load_admin_lookup()

    # Collect existing non-robbrad entries to preserve them
    non_robbrad_lookup = {k: v for k, v in admin_lookup.items() if not v.startswith("robbrad_")}
    new_robbrad_lookup = {}

    logger.info(f"Loaded {len(non_robbrad_lookup)} existing non-robbrad councils from lookup.")

    count_added = 0
    count_skipped_selenium = 0
    count_skipped_existing = 0
    count_skipped_blocked_domain = 0

    for council_name, data in input_data.items():
        if not isinstance(data, dict):
            continue

        url = data.get("url")
        if not url:
            url = data.get("wiki_url")
        if not url:
            continue

        domain = normalise_domain(url)

        # Skip blocked domains
        if domain in BLOCKED_DOMAINS:
            count_skipped_blocked_domain += 1
            continue

        # Check if already covered by a non-robbrad (mampfes) scraper
        if domain in non_robbrad_lookup:
            count_skipped_existing += 1
            continue

        # Check source file exists
        source_file = councils_dir / f"{council_name}.py"
        if not source_file.exists():
            logger.warning(f"Source file not found for {council_name}")
            continue

        if is_selenium_scraper(source_file):
            count_skipped_selenium += 1
            continue

        # Valid candidate
        logger.info(f"Adding new scraper: {council_name} ({domain})")

        source_code = source_file.read_text()

        # Rewrite imports to local shims
        new_source = rewrite_imports(source_code)

        # Convert requests → httpx (sync)
        new_source = convert_requests_to_httpx_sync(new_source)

        # Find class name
        try:
            tree = ast.parse(new_source)
            class_name = get_class_name(tree)
        except SyntaxError:
            class_name = None

        if not class_name:
            logger.warning(f"Could not find class in {council_name}, skipping.")
            continue

        # Detect params from input.json
        params = detect_init_params(data)

        # Derive human-readable title
        title = data.get("wiki_name", "")
        if not title:
            # CamelCase → spaced: "AberdeenCityCouncil" → "Aberdeen City Council"
            title = re.sub(r"(?<!^)(?=[A-Z])", " ", council_name)

        # Append adapter
        adapter = generate_adapter_code(class_name, params, url, title)
        final_source = new_source + adapter

        # Sanitize name to snake_case
        sanitized_name = "robbrad_" + re.sub(r"(?<!^)(?=[A-Z])", "_", council_name).lower()
        target_file = target_dir / f"{sanitized_name}.py"

        target_file.write_text(final_source)
        count_added += 1

        # Update lookup
        new_robbrad_lookup[domain] = sanitized_name

    # Merge lookups: non-robbrad entries + new robbrad entries
    merged_lookup = {**non_robbrad_lookup, **new_robbrad_lookup}

    if count_added > 0:
        logger.info(f"Updating admin_scraper_lookup.json with {count_added} new robbrad entries...")
        ADMIN_LOOKUP_PATH.write_text(json.dumps(merged_lookup, indent="\t", sort_keys=True))

    logger.info("Summary:")
    logger.info(f"  Added: {count_added}")
    logger.info(f"  Skipped (Existing/Mampfes): {count_skipped_existing}")
    logger.info(f"  Skipped (Selenium): {count_skipped_selenium}")
    logger.info(f"  Skipped (Blocked domain): {count_skipped_blocked_domain}")


if __name__ == "__main__":
    main()
