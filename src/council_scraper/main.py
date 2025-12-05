"""CLI entry point for the bin collection scraper."""

import asyncio

import typer

from .models import Config
from .runner import Runner

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


@app.command()
def preflight(
    councils: str = typer.Option(
        "data/postcodes_by_council.csv",
        "--councils",
        help="Path to council list",
    ),
    output: str = typer.Option(
        "output/",
        "--output",
        help="Output directory for results",
    ),
):
    """Run preflight validation only."""
    config = Config()
    runner = Runner(councils, output, config)

    async def main():
        runner._load_councils()
        results = await runner._run_preflight()
        runner._save_preflight_report(results)

        reachable = sum(1 for r in results if r.url_reachable)
        valid = sum(1 for r in results if r.postcode_valid)
        will_skip = sum(1 for r in results if r.skip_reason)

        print("✓ Preflight check complete:")
        print(f"  - Total councils: {len(results)}")
        print(f"  - URLs reachable: {reachable}")
        print(f"  - Valid postcodes: {valid}")
        print(f"  - Will skip: {will_skip}")

    asyncio.run(main())


if __name__ == "__main__":
    app()
