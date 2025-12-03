"""
Top-level orchestration script for building the council waste collection dataset.

This script coordinates the entire pipeline:
1. Loads postcode and population data
2. Fetches council URLs from GOV.UK
3. Scrapes council websites for waste collection URLs (sitemaps + homepage fallback)
4. Merges all data sources
5. Selects representative postcodes for each council
6. Saves the final dataset to CSV

Usage:
    uv run python -m src.finding_data.build_council_dataset
"""

import polars as pl
import asyncio
from pathlib import Path

from .postcode_data import get_populous_postcodes
from .council_url_scraper import CouncilURLScraper, get_council_urls


async def main(output_filename: str = "data/postcodes_by_council.csv") -> pl.DataFrame:
    """
    Main orchestration function that builds the complete council dataset.

    This function:
    1. Gets postcode and population data
    2. Fetches council URLs from GOV.UK
    3. Scrapes for waste collection URLs (with sitemap recursion and homepage fallback)
    4. Merges all data sources
    5. Selects a representative high-population postcode for each council
    6. Saves the results to CSV

    Args:
        output_filename: Path where the output CSV should be saved.
                        Defaults to "data/postcodes_by_council.csv"

    Returns:
        A Polars DataFrame containing the final merged data with columns:
            - Authority Name
            - URL: Council base URL
            - sitemap_url: Found sitemap URL (or None)
            - waste_collection_urls: Pipe-separated list of waste collection URLs
            - postcode: A representative postcode for the council area
    """
    print("\n" + "="*80)
    print("Starting Council Waste Collection Dataset Build")
    print("="*80 + "\n")

    # Step 1: Get postcode and population data
    print("Step 1/5: Loading postcode and population data...")
    postcode_merge = get_populous_postcodes()
    print(f"Loaded {len(postcode_merge):,} postcodes with population data\n")

    # Step 2: Get council URLs from GOV.UK
    print("Step 2/5: Fetching council URLs from GOV.UK...")
    council_urls_df = get_council_urls()
    print(f"Found {len(council_urls_df)} council URLs\n")

    # Step 3: Scrape for waste URLs using the class
    print("Step 3/5: Scraping council websites for waste collection URLs...")
    print("(This includes sitemap parsing with recursion and homepage fallback)")
    scraper = CouncilURLScraper(batch_size=10)
    council_urls_df = await scraper.process_all_councils(council_urls_df)

    # Count how many councils have waste URLs
    councils_with_urls = council_urls_df.filter(
        pl.col("waste_collection_urls").list.len() > 0
    )
    print(f"\nSuccessfully found waste URLs for {len(councils_with_urls)}/{len(council_urls_df)} councils")
    print(f"Coverage: {len(councils_with_urls)/len(council_urls_df)*100:.1f}%\n")

    # Step 4: Convert list column to pipe-separated string for CSV storage
    print("Step 4/5: Preparing data for export...")
    council_urls_df = council_urls_df.with_columns(
        pl.col("waste_collection_urls")
        .list.join("|")
        .fill_null("")
        .alias("waste_collection_urls")
    )

    # Step 5: Merge with postcode data and select representative postcodes
    print("Step 5/5: Merging with postcode data and selecting representative postcodes...")
    merged_df = (
        council_urls_df.join(postcode_merge, left_on="GSS", right_on="laua", how="left")
        .group_by("Authority Name", "URL", "sitemap_url", "waste_collection_urls")
        .agg([
            pl.col("postcode")
            .filter(pl.col("population") >= pl.col("population").quantile(0.5))
            .first()
            .alias("postcode"),
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
