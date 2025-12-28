"""CLI interface for bin lookup service"""

import sys
import traceback


from .bin_lookup import BinLookup, COUNCILS_DIR
from .utils import list_available_councils


def main():
    """Simple CLI for testing bin lookup"""
    if len(sys.argv) < 2:
        print("Usage: python src/main.py <council_name> [key=value ...]")
        print("\nAvailable councils:")
        for council in list_available_councils(COUNCILS_DIR)[:10]:
            print(f"  - {council}")
        print("  ...")
        return

    council_name = sys.argv[1]

    # Parse key=value inputs
    inputs = {}
    for arg in sys.argv[2:]:
        if "=" in arg:
            key, value = arg.split("=", 1)
            inputs[key] = value

    try:
        print(f"Looking up bin times for: {council_name}")
        print(f"Inputs: {inputs}\n")

        # Create BinLookup instance and perform lookup
        lookup = BinLookup()
        response = lookup.lookup(council_name, inputs)

        print(f"Status: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        print("\nResponse preview:")
        print(response.text[:1000])

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
