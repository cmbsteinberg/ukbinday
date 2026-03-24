#!/usr/bin/env python3
"""
Patch and integrate RobBrad scrapers into the API.

Reads input.json from the cloned RobBrad repo, filters out scrapers that
are already covered by Mampfes or use Selenium, adapts them to the
Project Source API, and patches them to use httpx if possible.
"""

import ast
import json
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

# Add mampfes patch script to path
MAMPFES_DIR = Path(__file__).resolve().parent.parent / "mampfes"
sys.path.append(str(MAMPFES_DIR))

try:
    from patch_scrapers import transform_source
except ImportError:
    print("Error: Could not import transform_source from patch_scrapers.py")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
API_DIR = PROJECT_ROOT / "api"
SCRAPERS_DIR = API_DIR / "scrapers"
ADMIN_LOOKUP_PATH = API_DIR / "data" / "admin_scraper_lookup.json"

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

def generate_adapter_code(original_class_name: str, args: dict) -> str:
    """Generate the Source class adapter."""

    # Determine init args
    # RobBrad scrapers usually take args via command line, but the class
    # structure varies. We'll assume a standard pattern or inspection.
    # For now, we'll accept common ones.

    init_args = []
    if "uprn" in args:
        init_args.append("uprn: str | None = None")
    if "postcode" in args:
        init_args.append("postcode: str | None = None")
    if "house_number" in args:
        init_args.append("house_number: str | None = None")
    if "usrn" in args:
        init_args.append("usrn: str | None = None")

    init_sig = ", ".join(["self"] + init_args)

    # We need to adapt the return value.
    # RobBrad returns: {"bins": [{"type": "...", "collectionDate": "..."}]}
    # We need: list[Collection]

    code = f"""

# --- Adapter for Project API ---
from waste_collection_schedule import Collection

class Source:
    def __init__({init_sig}):
        self.uprn = uprn
        self.postcode = postcode
        self.house_number = house_number
        self.usrn = usrn
        self._scraper = {original_class_name}()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        # Run the synchronous scraper in a thread
        # We wrap the call to get_data or whichever method is the entry point
        # Heuristic: Most RobBrad scrapers seem to use 'get_data' or 'get_date_data'
        # But we need to check the specific class.
        # For this generic adapter, we assume 'get_data' or similar.

        # NOTE: This is a best-effort adapter.
        # You may need to manually adjust the method call if it differs.

        try:
             # Prepare kwargs
            kwargs = {{}}
            if self.postcode: kwargs['postcode'] = self.postcode
            if self.uprn: kwargs['uprn'] = self.uprn
            if self.house_number: kwargs['house_number'] = self.house_number
            if self.usrn: kwargs['usrn'] = self.usrn

            # Helper to run sync method
            def _run_scraper():
                # Try common method names
                if hasattr(self._scraper, 'get_data'):
                    return self._scraper.get_data(**kwargs)
                if hasattr(self._scraper, 'get_date_data'):
                     return self._scraper.get_date_data(**kwargs)
                raise NotImplementedError("Could not find fetch method on scraper")

            data = await asyncio.to_thread(_run_scraper)

            # Parse result
            # Expected format: {{ "bins": [ {{ "type": "...", "collectionDate": "..." }} ] }}

            entries = []
            if isinstance(data, dict) and "bins" in data:
                for item in data["bins"]:
                    bin_type = item.get("type")
                    date_str = item.get("collectionDate")

                    if not bin_type or not date_str:
                        continue

                    # Parse date (RobBrad uses various formats, but often YYYY-MM-DD or DD/MM/YYYY)
                    # We might need a robust parser.
                    # For now, assume generic parsing or pass string if allowed (Collection expects date obj)

                    try:
                        # naive attempt at ISO
                        if "-" in date_str:
                             dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                        elif "/" in date_str:
                             dt = datetime.strptime(date_str, "%d/%m/%Y").date()
                        else:
                            continue # skip unparseable

                        entries.append(Collection(date=dt, t=bin_type, icon=None))
                    except ValueError:
                        continue

            return entries

        except Exception as e:
            # Log error
            print(f"Scraper failed: {{e}}")
            raise
"""
    return code


def main():
    if len(sys.argv) < 3:
        print("Usage: python patch_robbrad_scrapers.py <CLONE_DIR> <SCRAPERS_DIR>")
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

    logger.info(f"Loaded {len(admin_lookup)} existing councils from lookup.")
    # input.json is a dict where key is council name? Or list?
    # Based on search result it seemed to be a test config.
    # Let's inspect the structure. If it's a dict:

    items = []
    if isinstance(input_data, dict):
        items = input_data.items()
    elif isinstance(input_data, list):
        # Maybe list of dicts?
        pass

    # Heuristic: Inspect just one entry to see structure if possible?
    # No, we have to write the code.
    # Assume it's a dict mapping "CouncilName" -> { "url": "...", "postcode": "..." } based on typical test inputs.

    count_added = 0
    count_skipped_selenium = 0
    count_skipped_existing = 0

    for council_name, data in items:
        if not isinstance(data, dict):
            continue

        url = data.get("url")
        if not url:
            url = data.get("wiki_url") # Fallback

        if not url:
            continue

        domain = normalise_domain(url)

        # Check if exists
        if domain in admin_lookup:
            count_skipped_existing += 1
            continue

        # Check source file
        # RobBrad structure: uk_bin_collection/uk_bin_collection/councils/CouncilName.py
        source_file = councils_dir / f"{council_name}.py"
        if not source_file.exists():
            # Try lowercase or snake_case
            pass

        if not source_file.exists():
            logger.warning(f"Source file not found for {council_name}")
            continue

        if is_selenium_scraper(source_file):
            count_skipped_selenium += 1
            continue

        # Valid candidate
        logger.info(f"Adding new scraper: {council_name} ({domain})")

        # Read source
        source_code = source_file.read_text()

        # Transform (requests -> httpx)
        new_source, warnings = transform_source(source_code)

        # Find class name
        try:
            tree = ast.parse(new_source)
            class_name = get_class_name(tree)
        except SyntaxError:
            class_name = None

        if not class_name:
            logger.warning(f"Could not find class in {council_name}, skipping adapter generation.")
            # We still copy it? No, without adapter it won't work.
            continue

        # Append adapter
        adapter = generate_adapter_code(class_name, data)
        final_source = new_source + adapter

        # Add URL constant if missing (for generate_admin_lookup)
        if "URL =" not in final_source:
             final_source = f'URL = "{url}"\n' + final_source

        # Save to target
        # Let's sanitize name to snake_case for consistency
        sanitized_name = "robbrad_" + re.sub(r'(?<!^)(?=[A-Z])', '_', council_name).lower()
        target_file = target_dir / f"{sanitized_name}.py"

        target_file.write_text(final_source)
        count_added += 1

        # Update lookup
        admin_lookup[domain] = sanitized_name

    # Save updated lookup
    if count_added > 0:
        logger.info(f"Updating admin_scraper_lookup.json with {count_added} new entries...")
        ADMIN_LOOKUP_PATH.write_text(json.dumps(admin_lookup, indent=2, sort_keys=True))

    logger.info("Summary:")
    logger.info(f"  Added: {count_added}")
    logger.info(f"  Skipped (Existing): {count_skipped_existing}")
    logger.info(f"  Skipped (Selenium): {count_skipped_selenium}")

if __name__ == "__main__":
    main()
