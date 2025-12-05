"""Runner for orchestrating the overall scraping process."""

import asyncio
import json
import re
from pathlib import Path

import aiohttp
from playwright.async_api import Browser, async_playwright
from rich.console import Console

from .models import Config, Council, PreflightResult, RunnerResult, SessionResult
from .recorder import Recorder
from .session import Session

console = Console()


class Runner:
    """Orchestrates the overall scraping process."""

    def __init__(
        self, council_list_path: str, output_dir: str, config: Config | None = None
    ):
        self.council_list_path = council_list_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or Config()
        self.councils: list[Council] = []
        self.results: list[SessionResult] = []

    async def run(self) -> RunnerResult:
        """Process all councils."""
        console.rule("[bold blue]Council Bin Scraper[/bold blue]")

        self._load_councils()
        console.log(f"[green]Loaded {len(self.councils)} councils[/green]")

        existing_results = self._load_existing_results()
        if existing_results:
            console.log(
                f"[yellow]Found {len(existing_results)} existing results[/yellow]"
            )

        # Run preflight validation
        console.log("[cyan]Running preflight validation...[/cyan]")
        preflight_results = await self._run_preflight()
        self._save_preflight_report(preflight_results)

        # Filter councils to process
        councils_to_process = [
            c
            for c in self.councils
            if c.council_id not in existing_results
            and not any(
                r.skip_reason for r in preflight_results if r.council_id == c.council_id
            )
        ]

        console.log(
            f"[bold]Processing {len(councils_to_process)} councils "
            f"(skipped {len(self.councils) - len(councils_to_process)})[/bold]"
        )

        # Run browser and process councils
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.config.headless)
            try:
                for i, council in enumerate(councils_to_process):
                    console.rule(f"Council {i + 1}/{len(councils_to_process)}")

                    # Add delay between councils to avoid rate limiting (except first)
                    if i > 0 and self.config.inter_council_delay_ms > 0:
                        delay_seconds = self.config.inter_council_delay_ms / 1000
                        console.log(
                            f"[dim]Rate limit delay: {delay_seconds:.1f}s[/dim]"
                        )
                        await asyncio.sleep(delay_seconds)

                    result = await self.run_single(browser, council)
                    self.results.append(result)

                    status_color = "green" if result.status == "success" else "red"
                    console.log(
                        f"[{status_color}]{council.council_id}: {result.status}[/{status_color}]"
                    )
            finally:
                await browser.close()

        # Generate report
        self._generate_report()

        success_count = sum(1 for r in self.results if r.status == "success")
        failure_count = sum(1 for r in self.results if r.status == "failure")

        console.rule("[bold blue]Summary[/bold blue]")
        console.log(f"[green]✓ Success: {success_count}[/green]")
        console.log(f"[red]✗ Failed: {failure_count}[/red]")
        console.log(
            f"[yellow]⊘ Skipped: {len(self.councils) - len(self.results)}[/yellow]"
        )

        return RunnerResult(
            success_count=success_count,
            failure_count=failure_count,
            skipped_count=len(self.councils) - len(self.results),
            results=self.results,
        )

    async def run_single(self, browser: Browser, council: Council) -> SessionResult:
        """Process a single council."""
        context = await browser.new_context(
            viewport={
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )

        try:
            page = await context.new_page()
            recorder = Recorder(str(self.output_dir), council.council_id)
            recorder.setup_network_capture(page)

            session = Session(page, council, self.config, recorder)
            result = await session.run()

            recorder.close()
            return result
        except Exception as e:
            return SessionResult(
                status="failure",
                council_id=council.council_id,
                final_url="",
                iterations=0,
                history=[],
                failure_detail=str(e),
            )
        finally:
            await context.close()

    async def _run_preflight(self) -> list[PreflightResult]:
        """Validate councils before processing."""
        results = []

        for council in self.councils:
            result = await self._preflight_check(council)
            results.append(result)

        return results

    async def _preflight_check(self, council: Council) -> PreflightResult:
        """Quick validation before full exploration."""
        issues = []

        # Validate postcode format
        postcode_valid = bool(
            re.match(
                r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", council.test_postcode.upper()
            )
        )
        if not postcode_valid:
            issues.append("invalid_postcode_format")

        # Check URL is reachable
        url_reachable = False
        http_status = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(
                    council.url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    http_status = resp.status
                    url_reachable = resp.status < 400
        except Exception:
            url_reachable = False
            issues.append("url_unreachable")

        # Determine skip reason
        skip_reason = None
        if not url_reachable:
            skip_reason = "URL not reachable"
        elif not postcode_valid:
            skip_reason = "Invalid test postcode"

        return PreflightResult(
            council_id=council.council_id,
            url_reachable=url_reachable,
            http_status=http_status,
            postcode_valid=postcode_valid,
            detected_issues=issues,
            skip_reason=skip_reason,
        )

    def _load_councils(self) -> None:
        """Load council list from file."""
        with open(self.council_list_path) as f:
            if self.council_list_path.endswith(".csv"):
                # Parse CSV
                import csv

                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("URL") and row.get("postcode"):
                        self.councils.append(
                            Council(
                                council_id=row["Authority Name"]
                                .lower()
                                .replace(" ", "_")[:30],
                                name=row["Authority Name"],
                                url=row["URL"],
                                test_postcode=row["postcode"],
                                test_address=row.get("Address"),
                            )
                        )
            else:
                # Parse JSON
                data = json.load(f)
                for item in data:
                    self.councils.append(
                        Council(
                            council_id=item["council_id"],
                            name=item["name"],
                            url=item["url"],
                            test_postcode=item["test_postcode"],
                            test_address=item.get("test_address"),
                        )
                    )

    def _load_existing_results(self) -> set[str]:
        """Return council IDs already processed."""
        processed = set()
        for council_dir in self.output_dir.iterdir():
            if council_dir.is_dir() and (council_dir / "observations.jsonl").exists():
                processed.add(council_dir.name)
        return processed

    def _save_preflight_report(self, results: list[PreflightResult]) -> None:
        """Save preflight validation report."""
        report = {
            "total": len(results),
            "reachable": sum(1 for r in results if r.url_reachable),
            "valid_postcodes": sum(1 for r in results if r.postcode_valid),
            "will_skip": sum(1 for r in results if r.skip_reason),
            "details": [
                {
                    "council_id": r.council_id,
                    "url_reachable": r.url_reachable,
                    "http_status": r.http_status,
                    "postcode_valid": r.postcode_valid,
                    "issues": r.detected_issues,
                    "skip_reason": r.skip_reason,
                }
                for r in results
            ],
        }

        with open(self.output_dir / "preflight_report.json", "w") as f:
            json.dump(report, f, indent=2)

    def _generate_report(self) -> None:
        """Generate summary report."""
        from datetime import datetime

        report = {
            "timestamp": datetime.now().isoformat(),
            "total_processed": len(self.results),
            "successful": sum(1 for r in self.results if r.status == "success"),
            "failed": sum(1 for r in self.results if r.status == "failure"),
            "results": [
                {
                    "council_id": r.council_id,
                    "status": r.status,
                    "iterations": r.iterations,
                    "failure_category": r.failure_category.value
                    if r.failure_category
                    else None,
                    "failure_detail": r.failure_detail,
                    "is_recoverable": r.is_recoverable,
                }
                for r in self.results
            ],
        }

        with open(self.output_dir / "summary_report.json", "w") as f:
            json.dump(report, f, indent=2)
