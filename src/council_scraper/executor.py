"""Executor for performing actions on the page."""

import time

from playwright.async_api import Error, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from rich.console import Console

from .models import Action, Config, ExecutionResult

console = Console()


class Executor:
    """Executes actions on the page reliably."""

    def __init__(self, config: Config):
        self.config = config

    async def execute(self, page: Page, action: Action) -> ExecutionResult:
        """Execute an action on the page."""
        start_time = time.time()

        console.log(
            f"[cyan]→ Executing: {action.description or action.action_type}[/cyan]"
        )

        try:
            if action.action_type == "fill":
                result = await self._execute_fill(page, action)
            elif action.action_type == "click":
                result = await self._execute_click(page, action)
            elif action.action_type == "select":
                result = await self._execute_select(page, action)
            elif action.action_type == "wait":
                result = await self._execute_wait(page, action)
            else:
                result = ExecutionResult(
                    success=False,
                    action=action,
                    error_type="unknown_action_type",
                )

            result.duration_ms = int((time.time() - start_time) * 1000)

            if result.success:
                console.log(f"[green]✓ Success ({result.duration_ms}ms)[/green]")
            else:
                console.log(
                    f"[red]✗ Failed: {result.error_type} - {result.error_message}[/red]"
                )

            return result

        except Exception as e:
            console.log(f"[red]✗ Exception: {e}[/red]")
            return ExecutionResult(
                success=False,
                action=action,
                error_type="exception",
                error_message=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def _execute_fill(self, page: Page, action: Action) -> ExecutionResult:
        """Fill a text input."""
        try:
            element = page.locator(action.selector)

            # Ensure element is ready
            await element.wait_for(
                state="visible", timeout=self.config.element_timeout_ms
            )

            # Scroll into view
            await element.scroll_into_view_if_needed()

            # Clear existing value and type new value
            await element.clear()
            await element.type(action.value or "", delay=self.config.typing_delay_ms)

            return ExecutionResult(success=True, action=action)

        except PlaywrightTimeoutError:
            return ExecutionResult(
                success=False,
                action=action,
                error_type="timeout",
                error_message=f"Element {action.selector} not visible within timeout",
            )
        except Error as e:
            return ExecutionResult(
                success=False,
                action=action,
                error_type="playwright_error",
                error_message=str(e),
            )

    async def _execute_click(self, page: Page, action: Action) -> ExecutionResult:
        """Click an element."""
        try:
            element = page.locator(action.selector)

            await element.wait_for(
                state="visible", timeout=self.config.element_timeout_ms
            )
            await element.scroll_into_view_if_needed()

            # Use force=False to ensure element is actually clickable
            await element.click(timeout=self.config.click_timeout_ms, force=False)

            return ExecutionResult(success=True, action=action)

        except PlaywrightTimeoutError:
            return ExecutionResult(
                success=False,
                action=action,
                error_type="timeout",
                error_message=f"Element {action.selector} timeout",
            )
        except Error as e:
            if "intercept" in str(e).lower():
                return ExecutionResult(
                    success=False,
                    action=action,
                    error_type="click_intercepted",
                    error_message="Click was intercepted by another element",
                )
            return ExecutionResult(
                success=False,
                action=action,
                error_type="playwright_error",
                error_message=str(e),
            )

    async def _execute_select(self, page: Page, action: Action) -> ExecutionResult:
        """Select an option from a dropdown."""
        try:
            element = page.locator(action.selector)
            await element.wait_for(
                state="visible", timeout=self.config.element_timeout_ms
            )

            # Try selecting by value first, then by label
            try:
                await element.select_option(value=action.value)
            except Exception:
                await element.select_option(label=action.value)

            return ExecutionResult(success=True, action=action)

        except PlaywrightTimeoutError:
            return ExecutionResult(
                success=False,
                action=action,
                error_type="timeout",
                error_message=f"Element {action.selector} timeout",
            )
        except Error as e:
            return ExecutionResult(
                success=False,
                action=action,
                error_type="playwright_error",
                error_message=str(e),
            )

    async def _execute_wait(self, page: Page, action: Action) -> ExecutionResult:
        """Explicit wait, used sparingly."""
        try:
            wait_ms = int(action.value or 1000)
            await page.wait_for_timeout(wait_ms)
            return ExecutionResult(success=True, action=action)
        except Exception as e:
            return ExecutionResult(
                success=False,
                action=action,
                error_type="wait_error",
                error_message=str(e),
            )
