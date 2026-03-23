"""
Generate a JSON file of test cases extracted from each scraper module.

Reads the TEST_CASES constant from each scraper in scrapers/, and writes
a mapping of scraper_name -> list of test case param dicts to test_cases.json.

Each entry includes the council (scraper module name) and the params dict
so tests can call the API directly.
"""

import ast
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCRAPERS_DIR = Path(__file__).resolve().parent.parent.parent / "api" / "scrapers"
OUTPUT_PATH = Path(__file__).parent / "test_cases.json"


def extract_test_cases(path: Path) -> dict | None:
    """Parse the TEST_CASES = {...} constant from a scraper file using AST."""
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
            and node.targets[0].id == "TEST_CASES"
            and isinstance(node.value, ast.Dict)
        ):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError):
                logger.warning("Could not evaluate TEST_CASES in %s", path.name)
                return None
    return None


def main():
    output: dict[str, list[dict]] = {}
    no_tests: list[str] = []

    for path in sorted(SCRAPERS_DIR.glob("*.py")):
        scraper_name = path.stem
        cases = extract_test_cases(path)
        if not cases:
            no_tests.append(scraper_name)
            continue

        # Convert to list of {label, params} entries, stringifying all values
        entries = []
        for label, params in cases.items():
            str_params = {k: str(v) for k, v in params.items()}
            entries.append({"label": label, "params": str_params})

        output[scraper_name] = entries

    OUTPUT_PATH.write_text(json.dumps(output, indent=2, sort_keys=True))
    logger.info("Wrote test cases for %d scrapers to %s", len(output), OUTPUT_PATH)

    total_scrapers = len(list(SCRAPERS_DIR.glob("*.py")))
    print(f"\n{'=' * 50}")
    print("Test Cases Extraction Summary")
    print(f"{'=' * 50}")
    print(f"Total scrapers:          {total_scrapers}")
    print(f"With TEST_CASES:         {len(output)} ({len(output) * 100 // total_scrapers}%)")
    print(f"Without TEST_CASES:      {len(no_tests)}")
    total_cases = sum(len(v) for v in output.values())
    print(f"Total test cases:        {total_cases}")

    if no_tests:
        print("\nScrapers without TEST_CASES:")
        for name in no_tests:
            print(f"  {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
