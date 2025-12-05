"""Recorder for capturing network and session data."""

import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import aiofiles
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

        # File paths for async operations
        self._network_path = self.output_dir / "network.jsonl"
        self._action_path = self.output_dir / "actions.jsonl"
        self._observation_path = self.output_dir / "observations.jsonl"

        # Track pending requests with unique IDs to avoid race conditions
        self._pending_requests: dict[str, NetworkEntry] = {}
        self._request_id_map: dict[
            int, str
        ] = {}  # Maps Playwright request id to our UUID

        # Timeout for stale request cleanup (60 seconds)
        self._request_timeout_seconds = 60

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

            # Stream to disk immediately (schedule async write)
            asyncio.create_task(self._write_network_entry(entry))
        else:
            console.log(
                f"[yellow]Orphaned response (no matching request): {response.url}[/yellow]"
            )

    async def _write_network_entry(self, entry: NetworkEntry) -> None:
        """Append a network entry to the JSONL file."""
        async with aiofiles.open(self._network_path, "a") as f:
            await f.write(json.dumps(asdict(entry), default=str) + "\n")

    async def record_observation(self, observation: Observation) -> None:
        """Log an observation."""
        data = asdict(observation)
        # Convert timestamp to ISO format
        data["timestamp"] = observation.timestamp.isoformat()
        async with aiofiles.open(self._observation_path, "a") as f:
            await f.write(json.dumps(data, default=str) + "\n")

    async def record_action(self, action: Action, result: ExecutionResult) -> None:
        """Log an action and its result."""
        entry = {
            "action": asdict(action),
            "result": asdict(result),
            "timestamp": datetime.now().isoformat(),
        }
        async with aiofiles.open(self._action_path, "a") as f:
            await f.write(json.dumps(entry, default=str) + "\n")

    async def take_screenshot(self, page: Page, name: str) -> str:
        """Take a screenshot and return the path."""
        screenshots_dir = self.output_dir / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)
        path = screenshots_dir / f"{name}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)

    async def cleanup_stale_requests(self) -> None:
        """Clean up pending requests that are older than timeout threshold."""
        current_time = datetime.now()
        stale_uuids = []

        for request_uuid, entry in self._pending_requests.items():
            age_seconds = (current_time - entry.timestamp).total_seconds()
            if age_seconds > self._request_timeout_seconds:
                # Request is stale, write it without response data
                console.log(
                    f"[yellow]Stale request timeout ({age_seconds:.1f}s): {entry.request_url[:80]}[/yellow]"
                )
                await self._write_network_entry(entry)
                stale_uuids.append(request_uuid)

        # Remove stale entries
        for stale_uuid in stale_uuids:
            self._pending_requests.pop(stale_uuid, None)

        # Clean up orphaned request ID mappings
        # (when request objects are garbage collected but no response came)
        if len(self._request_id_map) > len(self._pending_requests) * 2:
            # If request_id_map is more than 2x the size of pending requests,
            # we likely have orphaned entries
            valid_uuids = set(self._pending_requests.keys())
            orphaned_ids = [
                req_id
                for req_id, uuid in self._request_id_map.items()
                if uuid not in valid_uuids
            ]
            for req_id in orphaned_ids:
                self._request_id_map.pop(req_id, None)

    def close(self) -> None:
        """Close recorder (no-op for async file operations)."""
        console.log(f"[dim]Recorder closed for {self.council_id}[/dim]")

    # Async context manager
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.close()
