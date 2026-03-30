"""
Generate a JSON mapping of council homepage domain -> scraper module name.

Reads the URL constant from each scraper in scrapers/, normalises to a
bare domain, and writes the mapping to admin_scraper_lookup.json.

At runtime, the gov.uk local authority API returns a homepage_url — normalise
that to a domain and look it up in this map to find the right scraper.
"""

import ast
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRAPERS_DIR = PROJECT_ROOT / "api" / "scrapers"
OUTPUT_PATH = PROJECT_ROOT / "api" / "data" / "admin_scraper_lookup.json"


def extract_url_from_scraper(path: Path) -> str | None:
    """Parse the URL = '...' constant from a scraper file using AST."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        logger.warning("Could not parse %s", path.name)
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


def normalise_domain(url: str) -> str:
    """Extract bare domain from a URL, stripping www. prefix and scheme."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def main():
    lookup: dict[str, str] = {}
    no_url: list[str] = []

    for path in sorted(SCRAPERS_DIR.glob("*.py")):
        scraper_name = path.stem
        url = extract_url_from_scraper(path)
        if not url:
            no_url.append(scraper_name)
            continue

        domain = normalise_domain(url)

        # North Yorkshire scrapers share northyorks.gov.uk but serve different
        # districts. Key them as "northyorks.gov.uk/hambleton" etc. so each
        # gets its own entry.
        if scraper_name.startswith("northyorks_") and "northyorks" in domain:
            # northyorks_selby_gov_uk -> "selby"
            district = scraper_name.split("_")[1]
            domain = f"{domain}/{district}"

        if domain in lookup:
            logger.warning(
                "Duplicate domain %s: %s and %s", domain, lookup[domain], scraper_name
            )
        lookup[domain] = scraper_name

    OUTPUT_PATH.write_text(json.dumps(lookup, indent=2, sort_keys=True))
    logger.info("Wrote %d domain -> scraper mappings to %s", len(lookup), OUTPUT_PATH)

    total_scrapers = len(list(SCRAPERS_DIR.glob("*.py")))
    print(f"\n{'=' * 50}")
    print("Domain -> Scraper Lookup Summary")
    print(f"{'=' * 50}")
    print(f"Total scrapers:       {total_scrapers}")
    print(
        f"Mapped (have URL):    {len(lookup)} ({len(lookup) * 100 // total_scrapers if total_scrapers else 0}%)"
    )
    print(f"Missing URL constant: {len(no_url)}")

    if no_url:
        print("\nScrapers without URL:")
        for name in no_url:
            print(f"  {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
