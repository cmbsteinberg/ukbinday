"""
Script for downloading and preparing the National Statistics Postcode Lookup (NSPL) data.

This script downloads the NSPL dataset, extracts the required postcode (pcd) and
local authority (laua) columns, and saves the result as a parquet file for fast
loading in other scripts.

Run this script once to prepare the postcode data:
    python src/finding_data/download_nspl.py
"""

import polars as pl
from io import BytesIO
import zipfile
import httpx
from pathlib import Path


def download_and_prepare_nspl(
    nspl_url: str = "https://www.arcgis.com/sharing/rest/content/items/077631e063eb4e1ab43575d01381ec33/data",
    output_path: str = "data/nspl.parquet",
) -> None:
    """
    Downloads and extracts the latest National Statistics Postcode Lookup (NSPL) data.

    Uses httpx for streaming download and optimized Polars settings for faster processing.
    Saves the result as a parquet file containing only postcode (pcd) and local authority
    (laua) columns.

    Args:
        nspl_url: URL to download the NSPL data from. Defaults to the official ArcGIS endpoint.
        output_path: Path where the parquet file should be saved. Defaults to data/nspl.parquet.

    Raises:
        httpx.HTTPError: If the download fails.
        zipfile.BadZipFile: If the downloaded file is not a valid zip file.
    """
    print("Downloading NSPL postcode data...")

    # Use httpx with streaming for better performance
    with httpx.stream("GET", nspl_url, follow_redirects=True) as response:
        response.raise_for_status()
        content = response.read()

    zip_buffer = BytesIO(content)
    print("Download complete.")

    with zipfile.ZipFile(zip_buffer, "r") as zip_file:
        # Find the UK-wide CSV file, which is the largest CSV in the 'Data' folder
        csv_file_name = max(
            (
                f
                for f in zip_file.infolist()
                if f.filename.startswith("Data/") and f.filename.endswith(".csv")
            ),
            key=lambda f: f.file_size,
        ).filename

        print(f"Reading from: {csv_file_name}")
        with zip_file.open(csv_file_name) as csv_file:
            # Select only the necessary columns to reduce memory usage
            # Use optimized Polars settings for faster parsing
            postcodes_full = pl.read_csv(
                csv_file,
                columns=["pcd", "laua"],
                low_memory=False,  # Faster parsing
                rechunk=True,  # Optimize memory layout for subsequent operations
            )

    # Ensure output directory exists
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Save as parquet for fast loading
    print(f"Saving to {output_path}...")
    postcodes_full.write_parquet(output_path)
    print(f"Successfully saved {len(postcodes_full):,} postcodes to {output_path}")


if __name__ == "__main__":
    download_and_prepare_nspl()
