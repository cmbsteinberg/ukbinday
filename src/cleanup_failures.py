import os
import json
import shutil
from pathlib import Path
import logging

logger = logging.getLogger().setLevel(logging.INFO)


def check_and_cleanup_council_dirs(
    base_path="data/traces",
    subdir="traces",
    results_json="result.json",
):
    """
    Check council subdirectories and delete them if:
    1. They don't contain a 'traces' folder with files, OR
    2. They contain results.json with '403 forbidden' in json.output.notes
    """
    base_dir = Path(base_path)

    if not base_dir.exists():
        print(f"Base directory {base_path} does not exist")
        return

    # Get all subdirectories in the base path
    council_dirs = [d for d in base_dir.iterdir() if d.is_dir()]

    for council_dir in council_dirs:
        should_delete = False
        delete_reason = ""

        print(f"Checking {council_dir.name}...")

        # Check 1: Does it contain a 'traces' folder with files?
        traces_dir = council_dir / subdir
        if not traces_dir.exists() or not traces_dir.is_dir():
            should_delete = True
            delete_reason = "No traces directory found"
        else:
            # Check if traces directory has any files
            trace_files = list(traces_dir.iterdir())
            if not trace_files:
                should_delete = True
                delete_reason = "Traces directory is empty"

        # Check 2: Does results.json exist and contain "403 forbidden" in output.notes?
        if not should_delete:  # Only check if we haven't already decided to delete
            results_file = council_dir / results_json
            if results_file.exists():
                try:
                    with open(results_file, "r", encoding="utf-8") as f:
                        results_data = json.load(f)

                    # Navigate to output.notes
                    output_data = results_data.get("output", {})
                    notes = output_data.get("notes")

                    if isinstance(notes, str):
                        # List of strings to search for (case-insensitive)
                        search_strings = [
                            "403 forbidden",
                            "404 not found",
                            "500 internal server error",
                            "CAPTCHA",
                        ]
                        notes_lower = notes.lower()

                        for search_string in search_strings:
                            if search_string in notes_lower:
                                should_delete = True
                                delete_reason = f"Found '{search_string}' in results.json output.notes"
                                break

                except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
                    logging.info(
                        f"  Warning: Could not read results.json in {council_dir.name}: {e}"
                    )
            else:
                should_delete = True
        # Delete the directory if conditions are met
        if should_delete:
            try:
                shutil.rmtree(council_dir)
                logging.info(
                    f"  ✓ Deleted {council_dir.name} - Reason: {delete_reason}"
                )
            except Exception as e:
                print(f"  ✗ Failed to delete {council_dir.name}: {e}")
        else:
            logging.info(f"  ✓ Keeping {council_dir.name} - Directory is valid")


def main():
    """
    Main function to run the cleanup process
    """
    print("Starting council directory cleanup...")
    check_and_cleanup_council_dirs()
    print("Cleanup complete!")


if __name__ == "__main__":
    main()
