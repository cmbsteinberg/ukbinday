"""Recorder for capturing network and session data."""

import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, Request, Response
from rich.console import Console

from .models import Action, ExecutionResult, NetworkEntry, Observation

console = Console()


class Recorder:
    """Records all activity for later analysis."""

    def __init__(self, output_dir: str, council_id: str):
        self.output_dir = Path(output_dir) / council_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.council_id = council_id

        # Open file handles for streaming writes
        self._network_file = open(self.output_dir / "network.jsonl", "a")
        self._action_file = open(self.output_dir / "actions.jsonl", "a")
        self._observation_file = open(self.output_dir / "observations.jsonl", "a")

        # Track pending requests with unique IDs to avoid race conditions
        self._pending_requests: dict[str, NetworkEntry] = {}
        self._request_id_map: dict[
            int, str
        ] = {}  # Maps Playwright request id to our UUID

        console.log(f"[dim]Recorder initialized for {council_id}[/dim]")

    def setup_network_capture(self, page: Page) -> None:
        """Attach network event handlers to the page."""
        page.on("request", self._on_request)
        # Properly handle async response handler using asyncio
        page.on(
            "response",
            lambda response: asyncio.create_task(self._on_response(response)),
        )

    def _on_request(self, request: Request) -> None:
        """Handle outgoing request - synchronous event handler."""
        # Generate unique ID for this request to avoid race conditions
        request_uuid = str(uuid.uuid4())

        entry = NetworkEntry(
            timestamp=datetime.now(),
            request_url=request.url,
            request_method=request.method,
            request_headers=dict(request.headers),
            request_body=request.post_data,
            response_status=None,
            response_headers=None,
            response_body=None,
            duration_ms=0,
            resource_type=request.resource_type,
        )

        # Store with UUID and map Playwright's request hash to our UUID
        self._pending_requests[request_uuid] = entry
        # Use request object's hash as identifier
        self._request_id_map[id(request)] = request_uuid

    async def _on_response(self, response: Response) -> None:
        """Handle incoming response - async to capture response body."""
        # Match response to request using Playwright's request object
        request_id = id(response.request)
        request_uuid = self._request_id_map.pop(request_id, None)

        if request_uuid and request_uuid in self._pending_requests:
            entry = self._pending_requests.pop(request_uuid)
            entry.response_status = response.status
            entry.response_headers = dict(response.headers)
            entry.duration_ms = int(
                (datetime.now() - entry.timestamp).total_seconds() * 1000
            )

            # Capture response body for text-based content types
            content_type = response.headers.get("content-type", "")
            if any(
                t in content_type for t in ["json", "xml", "html", "text", "javascript"]
            ):
                try:
                    entry.response_body = await response.text()
                except Exception as e:
                    console.log(
                        f"[yellow]Could not capture response body for {response.url}: {e}[/yellow]"
                    )
                    entry.response_body = None

            # Stream to disk immediately
            self._write_network_entry(entry)
        else:
            console.log(
                f"[yellow]Orphaned response (no matching request): {response.url}[/yellow]"
            )

    def _write_network_entry(self, entry: NetworkEntry) -> None:
        """Append a network entry to the JSONL file."""
        self._network_file.write(json.dumps(asdict(entry), default=str) + "\n")
        self._network_file.flush()

    def record_observation(self, observation: Observation) -> None:
        """Log an observation."""
        data = asdict(observation)
        # Convert timestamp to ISO format
        data["timestamp"] = observation.timestamp.isoformat()
        self._observation_file.write(json.dumps(data, default=str) + "\n")
        self._observation_file.flush()

    def record_action(self, action: Action, result: ExecutionResult) -> None:
        """Log an action and its result."""
        entry = {
            "action": asdict(action),
            "result": asdict(result),
            "timestamp": datetime.now().isoformat(),
        }
        self._action_file.write(json.dumps(entry, default=str) + "\n")
        self._action_file.flush()

    async def take_screenshot(self, page: Page, name: str) -> str:
        """Take a screenshot and return the path."""
        screenshots_dir = self.output_dir / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)
        path = screenshots_dir / f"{name}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)

    def close(self) -> None:
        """Close file handles."""
        self._network_file.close()
        self._action_file.close()
        self._observation_file.close()
        console.log(f"[dim]Recorder closed for {self.council_id}[/dim]")

    # Sync context manager (deprecated, kept for compatibility)
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # Async context manager (proper)
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.close()
