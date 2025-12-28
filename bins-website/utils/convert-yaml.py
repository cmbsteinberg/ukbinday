#!/usr/bin/env python3
"""
Convert council YAML files to a single JSON file for the web app.
Only includes API-based councils (single_api, token_then_api, id_lookup_then_api).
"""

import yaml
import json
from pathlib import Path


def convert_yaml_to_json():
    """Convert all council YAML files to a single JSON file."""
    # Path to councils directory (relative to project root)
    councils_dir = Path(__file__).parent.parent / "src" / "councils"

    if not councils_dir.exists():
        print(f"Error: Councils directory not found: {councils_dir}")
        return

    councils = {}
    api_based_types = ["single_api", "token_then_api", "id_lookup_then_api"]

    # Process all YAML files
    yaml_files = list(councils_dir.glob("*.yaml"))
    print(f"Found {len(yaml_files)} YAML files")

    for yaml_file in yaml_files:
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            # Only include API-based councils (skip selenium and calendar)
            request_type = data.get("request_type", "")
            if request_type in api_based_types:
                council_name = data.get("council")
                if council_name:
                    councils[council_name] = data
        except Exception as e:
            print(f"Warning: Failed to process {yaml_file.name}: {e}")

    # Write to JSON file
    output_file = Path(__file__).parent / "councils-data.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(councils, f, indent=2, ensure_ascii=False)

    print(f"\nSuccess! Converted {len(councils)} API-based councils to {output_file}")
    print(f"File size: {output_file.stat().st_size / 1024:.1f} KB")

    # Print summary
    request_types = {}
    for council_data in councils.values():
        rt = council_data.get("request_type", "unknown")
        request_types[rt] = request_types.get(rt, 0) + 1

    print("\nBreakdown by request type:")
    for rt, count in sorted(request_types.items()):
        print(f"  {rt}: {count}")


if __name__ == "__main__":
    convert_yaml_to_json()
