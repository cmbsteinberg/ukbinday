import polars as pl
import subprocess
import sys
from pathlib import Path

OUTPUT_DIR = "./data/traces/{council_name}"


def main():
    """Reads council data and launches a separate process for each one."""
    try:
        councils = pl.read_csv("data/postcodes_by_council.csv").to_dicts()
        print(f"Found {len(councils)} councils to process.")

    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return

    for council in councils:
        # Ensure all required fields are present
        council_name = council.get("Authority Name")
        formatted_council_name = council_name.lower().replace(" ", "_")
        output_dir = OUTPUT_DIR.format(council_name=formatted_council_name)
        if council.get("postcode") and not Path(output_dir).exists():
            print(f"\n--- Starting process for: {council_name} ---")

            # Command to execute the worker script
            command = [
                sys.executable,  # Use the same python interpreter
                "src/run_single_council.py",
                "--output-dir",
                output_dir,
                "--url",
                council.get("URL"),
                "--postcode",
                council.get("postcode"),
            ]

            # Run the command in a separate process
            # `capture_output=True` and `text=True` help see the worker's output
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )

            # Print the output from the subprocess
            print(result.stdout)
            if result.stderr:
                print("--- Errors ---")
                print(result.stderr)
        else:
            print(f"Skipping row {council}")

    print("\nAll councils processed.")


if __name__ == "__main__":
    main()
