"""
Top-level orchestration script for building the council waste collection dataset.

This script coordinates the entire pipeline:
1. Loads postcode geographic data
2. Downloads Land Registry property data with addresses
3. Fetches council URLs from GOV.UK
4. Scrapes council websites for waste collection URLs (sitemaps + homepage fallback)
5. Merges all data sources
6. Selects representative addresses for each council
7. Saves the final dataset to CSV

Usage:
    uv run python -m src.finding_data.build_council_dataset
"""

import polars as pl
import asyncio
from pathlib import Path

from .postcode_data import get_postcode_data
from .household_waste_info import get_land_registry_data
from .council_url_scraper import CouncilURLScraper, get_council_urls


async def main(output_filename: str = "data/postcodes_by_council.csv") -> pl.DataFrame:
    """
    Main orchestration function that builds the complete council dataset.

    This function:
    1. Gets postcode geographic data (NSPL)
    2. Downloads Land Registry property data with addresses
    3. Fetches council URLs from GOV.UK
    4. Scrapes for waste collection URLs (with sitemap recursion and homepage fallback)
    5. Merges all data sources
    6. Selects a representative address for each council
    7. Saves the results to CSV

    Args:
        output_filename: Path where the output CSV should be saved.
                        Defaults to "data/postcodes_by_council.csv"

    Returns:
        A Polars DataFrame containing the final merged data with columns:
            - Authority Name: Name of the local authority/council
            - GSS: Government Statistical Service code
            - URL: Council base URL
            - sitemap_url: Found sitemap URL (or None)
            - waste_collection_urls: Pipe-separated list of waste collection URLs
            - Number: Property number (including flat/unit if applicable)
            - Street: Street name
            - Town: Town or city name
            - Address: Combined Number + Street
            - postcode: Corresponding postcode for the address
    """
    print("\n" + "="*80)
    print("Starting Council Waste Collection Dataset Build")
    print("="*80 + "\n")

    # Step 1: Get postcode geographic data
    print("Step 1/6: Loading postcode geographic data (NSPL)...")
    postcode_df = get_postcode_data()
    print(f"Loaded {len(postcode_df):,} postcodes with local authority mappings\n")

    # Step 2: Get Land Registry data with addresses
    print("Step 2/6: Downloading Land Registry property data...")
    land_registry_df = get_land_registry_data()
    print(f"Loaded {len(land_registry_df):,} property transactions with addresses\n")

    # Step 3: Get council URLs from GOV.UK
    print("Step 3/6: Fetching council URLs from GOV.UK...")
    council_urls_df = get_council_urls()
    print(f"Found {len(council_urls_df)} council URLs\n")

    # Step 4: Scrape for waste URLs using the class
    print("Step 4/6: Scraping council websites for waste collection URLs...")
    print("(This includes sitemap parsing with recursion and homepage fallback)")
    scraper = CouncilURLScraper(batch_size=10)
    council_urls_df = await scraper.process_all_councils(council_urls_df)

    # Count how many councils have waste URLs
    councils_with_urls = council_urls_df.filter(
        pl.col("waste_collection_urls").list.len() > 0
    )
    print(f"\nSuccessfully found waste URLs for {len(councils_with_urls)}/{len(council_urls_df)} councils")
    print(f"Coverage: {len(councils_with_urls)/len(council_urls_df)*100:.1f}%\n")

    # Step 5: Convert list column to pipe-separated string for CSV storage
    print("Step 5/6: Preparing data for export...")
    council_urls_df = council_urls_df.with_columns(
        pl.col("waste_collection_urls")
        .list.join("|")
        .fill_null("")
        .alias("waste_collection_urls")
    )

    # Step 6: Merge postcode data with Land Registry data to get addresses with local authorities
    print("Step 6/6: Merging postcode data with Land Registry addresses...")
    postcode_with_addresses = postcode_df.join(
        land_registry_df.select(["pcd", "postcode", "Number", "Street", "Town", "Address"]),
        on="pcd",
        how="inner"
    )
    print(f"Found {len(postcode_with_addresses):,} postcodes with addresses\n")

    # Merge with council data and select representative addresses
    print("Merging council data with postcodes and addresses...")
    merged_df = (
        council_urls_df.join(postcode_with_addresses, left_on="GSS", right_on="laua", how="left")
        .group_by("Authority Name", "URL", "sitemap_url", "waste_collection_urls", "GSS")
        .agg([
            # Select the first available postcode and address components
            pl.col("postcode").first().alias("postcode"),
            pl.col("Number").first().alias("Number"),
            pl.col("Street").first().alias("Street"),
            pl.col("Town").first().alias("Town"),
            pl.col("Address").first().alias("Address"),
        ])
        .select([
            "Authority Name",
            "GSS",
            "URL",
            "sitemap_url",
            "waste_collection_urls",
            "Number",
            "Street",
            "Town",
            "Address",
            "postcode",
        ])
    )

    # Save the final enriched data to a CSV
    output_path = Path(output_filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\nSaving final dataset to {output_filename}...")
    merged_df.write_csv(output_filename)

    print("\n" + "="*80)
    print("✅ Dataset build completed successfully!")
    print(f"   Output: {output_filename}")
    print(f"   Councils: {len(merged_df)}")
    print(f"   Councils with waste URLs: {len(councils_with_urls)}")
    print("="*80 + "\n")

    return merged_df


if __name__ == "__main__":
    # Run the main function
    output = asyncio.run(main())
