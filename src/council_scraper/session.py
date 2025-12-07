"""Session for exploring a single council website."""

import re

from playwright.async_api import Page
from rich.console import Console

from executor import Executor
from models import (
    Action,
    Config,
    Council,
    FailureCategory,
    HistoryEntry,
    Observation,
    SessionResult,
)
from observer import Observer
from recorder import Recorder
from strategist import Strategist

console = Console()

# Constants for detection thresholds
MIN_PAGE_TEXT_LENGTH = 50  # Minimum text length for non-empty page
LOOP_HISTORY_WINDOW = 10  # Look back window for loop detection
MAX_HASH_REPEATS = 3  # Max times same observation hash before declaring loop
UNPRODUCTIVE_ACTION_THRESHOLD = 5  # Max unproductive actions before declaring loop
PROGRESS_SCORE_THRESHOLD = 0.3  # Minimum average progress score to avoid loop


class Session:
    """Manages a single exploration attempt for one council."""

    def __init__(
        self,
        page: Page,
        council: Council,
        config: Config,
        recorder: Recorder,
    ):
        self.page = page
        self.council = council
        self.config = config
        self.recorder = recorder
        self.observer = Observer()
        self.strategist = Strategist(config)
        self.executor = Executor(config)
        self.history: list[HistoryEntry] = []
        self.phase = "initial"
        self._previous_selectors: set[str] = (
            set()
        )  # Track selectors for stateless observer

    async def run(self) -> SessionResult:
        """Main exploration loop."""
        console.rule(f"[bold cyan]Starting session for {self.council.name}[/bold cyan]")
        console.log(f"[dim]URL: {self.council.url}[/dim]")
        console.log(f"[dim]Test postcode: {self.council.test_postcode}[/dim]")

        try:
            # Navigate to start URL
            await self._navigate_to_start_url()

            # Main loop
            for iteration in range(self.config.max_iterations):
                console.log(
                    f"[bold]Iteration {iteration + 1}/{self.config.max_iterations}[/bold]"
                )

                # 1. Observe current state (pass previous selectors for stateless operation)
                observation = await self.observer.observe(
                    self.page, self._previous_selectors
                )
                await self.recorder.record_observation(observation)

                # Update selectors for next iteration
                self._previous_selectors = (
                    {inp.selector for inp in observation.inputs}
                    | {btn.selector for btn in observation.buttons}
                    | {link.selector for link in observation.links}
                )

                # 2. Check termination conditions
                if self._is_success(observation):
                    console.log(
                        "[bold green]✓ SUCCESS: Bin collection page detected![/bold green]"
                    )
                    # Take success screenshot if configured
                    if self.config.screenshot_on_success:
                        screenshot_path = await self.recorder.take_screenshot(
                            self.page, f"success_iteration_{iteration}"
                        )
                        console.log(f"[dim]Screenshot: {screenshot_path}[/dim]")

                    return SessionResult(
                        status="success",
                        council_id=self.council.council_id,
                        final_url=self.page.url,
                        iterations=iteration,
                        history=self.history,
                    )

                if self._is_dead_end(observation):
                    category, detail = self._classify_failure(observation, None, None)
                    console.log(f"[yellow]Dead end detected: {detail}[/yellow]")

                    # Take failure screenshot if configured
                    error_screenshots = []
                    if self.config.screenshot_on_failure:
                        screenshot_path = await self.recorder.take_screenshot(
                            self.page, f"failure_deadend_iteration_{iteration}"
                        )
                        error_screenshots.append(screenshot_path)
                        console.log(f"[dim]Screenshot: {screenshot_path}[/dim]")

                    return SessionResult(
                        status="failure",
                        council_id=self.council.council_id,
                        final_url=self.page.url,
                        iterations=iteration,
                        history=self.history,
                        failure_category=category,
                        failure_detail=detail,
                        is_recoverable=category
                        not in [
                            FailureCategory.CAPTCHA_PRESENT,
                            FailureCategory.LOGIN_REQUIRED,
                        ],
                        error_screenshots=error_screenshots,
                    )

                if self._is_loop(observation):
                    # Calculate final progress score for diagnostics
                    progress_score = (
                        self._calculate_recent_progress() if self.history else 0.0
                    )

                    error_screenshots = []
                    if self.config.screenshot_on_failure:
                        screenshot_path = await self.recorder.take_screenshot(
                            self.page, f"failure_loop_iteration_{iteration}"
                        )
                        error_screenshots.append(screenshot_path)

                    # Build detailed failure message
                    url_visits = sum(
                        1
                        for entry in self.history[-LOOP_HISTORY_WINDOW:]
                        if entry.observation.url == observation.url
                    )
                    failure_detail = f"Loop detected: visited {observation.url} {url_visits} times, progress score: {progress_score:.2f}"

                    return SessionResult(
                        status="failure",
                        council_id=self.council.council_id,
                        final_url=self.page.url,
                        iterations=iteration,
                        history=self.history,
                        failure_category=FailureCategory.LOOP_DETECTED,
                        failure_detail=failure_detail,
                        is_recoverable=True,
                        error_screenshots=error_screenshots,
                    )

                # 3. Get candidate actions
                test_data = self.council.get_test_data()
                candidates = self.strategist.get_actions(
                    observation, self.history, test_data
                )

                if not candidates:
                    console.log("[yellow]No more actions available[/yellow]")
                    return SessionResult(
                        status="failure",
                        council_id=self.council.council_id,
                        final_url=self.page.url,
                        iterations=iteration,
                        history=self.history,
                        failure_category=FailureCategory.NO_ACTIONS,
                        failure_detail="No more actions available",
                        is_recoverable=True,
                    )

                # 4. Execute top action
                action = candidates[0]
                console.log(
                    f"[dim]Confidence: {action.confidence:.2f}, Candidates: {len(candidates)}[/dim]"
                )
                result = await self.executor.execute(self.page, action)

                # 5. Record the action
                self.history.append(
                    HistoryEntry(observation=observation, action=action, result=result)
                )
                await self.recorder.record_action(action, result)

                if not result.success:
                    # Action failed, continue to next iteration to reassess
                    continue

                # 6. Wait for page to settle
                await self._wait_for_settle()

                # 7. Clean up stale network requests to prevent memory leak
                await self.recorder.cleanup_stale_requests()

            # Max iterations exceeded
            console.log(
                f"[red]Max iterations ({self.config.max_iterations}) exceeded[/red]"
            )

            error_screenshots = []
            if self.config.screenshot_on_failure:
                screenshot_path = await self.recorder.take_screenshot(
                    self.page, "failure_max_iterations"
                )
                error_screenshots.append(screenshot_path)

            return SessionResult(
                status="failure",
                council_id=self.council.council_id,
                final_url=self.page.url,
                iterations=self.config.max_iterations,
                history=self.history,
                failure_category=FailureCategory.MAX_ITERATIONS,
                failure_detail=f"Exceeded max iterations ({self.config.max_iterations})",
                is_recoverable=True,
                error_screenshots=error_screenshots,
            )

        except Exception as e:
            console.log(f"[red]Session exception: {e}[/red]")
            category, detail = self._classify_failure(None, None, e)
            return SessionResult(
                status="failure",
                council_id=self.council.council_id,
                final_url=self.page.url,
                iterations=len(self.history),
                history=self.history,
                failure_category=category,
                failure_detail=detail,
                is_recoverable=True,
            )

    async def _navigate_to_start_url(self) -> None:
        """Navigate to the council's bin lookup URL."""
        await self.page.goto(
            self.council.url,
            wait_until="load",
            timeout=self.config.page_load_timeout_ms,
        )
        await self._wait_for_settle()

    def _is_success(self, observation: Observation) -> bool:
        """Check if page indicates success."""
        if observation.contains_success_indicators:
            return True

        # Check for dates in near future (simple heuristic)
        text_lower = observation.visible_text_sample.lower()
        date_patterns = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "jan",
            "feb",
        ]
        if any(pattern in text_lower for pattern in date_patterns):
            # Also check for month/day pattern
            if re.search(
                r"\d{1,2}\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                text_lower,
            ):
                return True

        return False

    def _is_dead_end(self, observation: Observation) -> bool:
        """Check if we're in a dead end."""
        if observation.contains_error_message:
            return True

        # Check for specific error messages (not just "sign in" which is too broad)
        text_lower = observation.visible_text_sample.lower()
        dead_end_indicators = [
            "postcode not found",
            "invalid postcode",
            "no results found",
            "page not found",
            "404 error",
            "you must login",
            "you must sign in",
            "login required to access",
            "please log in to continue",
        ]

        if any(indicator in text_lower for indicator in dead_end_indicators):
            return True

        # If page is nearly empty (but not completely empty to avoid false positives)
        if len(observation.visible_text_sample.strip()) < MIN_PAGE_TEXT_LENGTH:
            return True

        return False

    def _is_loop(self, observation: Observation) -> bool:
        """Detect if we're in a loop using multiple heuristics."""
        if len(self.history) < 3:
            return False  # Need some history to detect loops

        # Heuristic 1: Check if we've visited the same URL many times
        url_count = sum(
            1
            for entry in self.history[-LOOP_HISTORY_WINDOW:]
            if entry.observation.url == observation.url
        )
        if url_count > self.config.max_same_url_visits:
            console.log(
                f"[yellow]Loop detected: visited {observation.url} {url_count} times[/yellow]"
            )
            return True

        # Heuristic 2: Check if we've seen the same observation hash recently
        current_hash = observation.hash
        hash_count = sum(
            1
            for entry in self.history[-LOOP_HISTORY_WINDOW:]
            if entry.observation.hash == current_hash
        )
        if hash_count > MAX_HASH_REPEATS:
            console.log(
                f"[yellow]Loop detected: same page state {hash_count} times[/yellow]"
            )
            return True

        # Heuristic 3: Check action effectiveness - are we making progress?
        if len(self.history) >= UNPRODUCTIVE_ACTION_THRESHOLD:
            recent_progress = self._calculate_recent_progress()
            if recent_progress < PROGRESS_SCORE_THRESHOLD:
                console.log(
                    f"[yellow]Loop detected: low progress score {recent_progress:.2f}[/yellow]"
                )
                return True

        return False

    def _calculate_recent_progress(self) -> float:
        """
        Calculate a progress score based on recent actions.
        Higher score = more progress being made.
        """
        if len(self.history) < 2:
            return 1.0

        recent_history = self.history[-UNPRODUCTIVE_ACTION_THRESHOLD:]
        progress_score = 0.0
        visited_urls = set()
        seen_hashes = set()

        for i, entry in enumerate(recent_history):
            # Track unique URLs and page states
            url = entry.observation.url
            page_hash = entry.observation.hash

            # Reward new URLs
            if url not in visited_urls:
                progress_score += 0.3
                visited_urls.add(url)

            # Reward new page states (different content)
            if page_hash not in seen_hashes:
                progress_score += 0.2
                seen_hashes.add(page_hash)

            # Reward new elements appearing
            if entry.observation.new_elements_since_last:
                progress_score += 0.1

            # Reward successful form fills (higher value actions)
            if entry.action.action_type == "fill" and entry.result.success:
                progress_score += 0.4

            # Reward clicks with high confidence
            if entry.action.confidence > 0.7:
                progress_score += 0.1

            # Penalize failed actions
            if not entry.result.success:
                progress_score -= 0.2

        # Normalize by number of actions
        return progress_score / len(recent_history) if recent_history else 0.0

    def _classify_failure(
        self,
        observation: Observation | None,
        last_action: Action | None,
        error: Exception | None,
    ) -> tuple[FailureCategory, str]:
        """Determine failure category from available evidence."""
        if observation:
            page_text = observation.visible_text_sample.lower()

            if any(
                phrase in page_text
                for phrase in ["captcha", "robot", "verify you're human"]
            ):
                return FailureCategory.CAPTCHA_PRESENT, "CAPTCHA detected on page"

            if any(
                phrase in page_text
                for phrase in ["sign in", "log in", "login required"]
            ):
                return FailureCategory.LOGIN_REQUIRED, "Login wall detected"

            if any(
                phrase in page_text
                for phrase in [
                    "postcode not found",
                    "invalid postcode",
                    "not recognised",
                ]
            ):
                return (
                    FailureCategory.POSTCODE_NOT_FOUND,
                    "Site rejected the test postcode",
                )

            if any(
                phrase in page_text for phrase in ["no addresses", "address not found"]
            ):
                return (
                    FailureCategory.ADDRESS_NOT_FOUND,
                    "No addresses found for postcode",
                )

            if "404" in page_text or observation.url.endswith("/404"):
                return FailureCategory.PAGE_NOT_FOUND, "Page not found (404)"

        if error:
            error_str = str(error).lower()
            if "net::" in error_str or "connection" in error_str:
                return FailureCategory.NETWORK_ERROR, str(error)
            if "crash" in error_str or "target closed" in error_str:
                return FailureCategory.BROWSER_CRASH, str(error)

        return FailureCategory.UNKNOWN, "Could not determine failure reason"

    async def _wait_for_settle(self) -> None:
        """Wait for page to be stable enough to observe."""
        try:
            # Wait for network idle with timeout
            await self.page.wait_for_load_state(
                "networkidle", timeout=self.config.settle_timeout_ms
            )
        except Exception:
            # Network didn't idle, but that's okay
            pass

        # Additional short wait for any final DOM updates
        await self.page.wait_for_timeout(self.config.settle_check_interval_ms)
