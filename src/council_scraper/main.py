"""CLI entry point for the bin collection scraper.

1. run - Execute the full bin collection scraper
   - --councils - Path to council list CSV/JSON (default: data/postcodes_by_council.csv)
   - --output - Output directory (default: output/)
   - --headless/--headed - Run browser headless or with UI (default: headless)
   - --max-iterations - Max iterations per council (default: 50)

Preflight checks (URL reachability, postcode validity) are run per-council during processing.
"""

import asyncio

import typer

from models import Config
from runner import Runner

app = typer.Typer()


@app.command()
def run(
    councils: str = typer.Option(
        "data/postcodes_by_council.csv",
        "--councils",
        help="Path to council list (CSV or JSON)",
    ),
    output: str = typer.Option(
        "output/",
        "--output",
        help="Output directory for results",
    ),
    headless: bool = typer.Option(
        True,
        "--headless/--headed",
        help="Run browser in headless mode",
    ),
    max_iterations: int = typer.Option(
        50,
        "--max-iterations",
        help="Max iterations per council",
    ),
):
    """Run the bin collection scraper."""
    config = Config(
        headless=headless,
        max_iterations=max_iterations,
    )

    runner = Runner(councils, output, config)

    async def main():
        result = await runner.run()
        print(
            f"\n✓ Processed {result.success_count} successful, {result.failure_count} failed, {result.skipped_count} skipped"
        )
        return result

    result = asyncio.run(main())
    return result


if __name__ == "__main__":
    app()
