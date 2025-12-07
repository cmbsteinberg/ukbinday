"""Data models for the bin collection scraper."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


class FailureCategory(Enum):
    """Categorise failures for better diagnostics and retry decisions."""

    # Recoverable - might work with different approach or retry
    TIMEOUT = "timeout"
    ELEMENT_NOT_FOUND = "element_not_found"
    LOOP_DETECTED = "loop_detected"
    NO_ACTIONS = "no_actions"
    MAX_ITERATIONS = "max_iterations"

    # Likely data issues - check council config
    POSTCODE_NOT_FOUND = "postcode_not_found"
    ADDRESS_NOT_FOUND = "address_not_found"
    INVALID_INPUT = "invalid_input"

    # Fundamental blockers - need manual intervention
    CAPTCHA_PRESENT = "captcha_present"
    LOGIN_REQUIRED = "login_required"
    PAGE_NOT_FOUND = "page_not_found"
    SITE_ERROR = "site_error"

    # Infrastructure issues
    NETWORK_ERROR = "network_error"
    BROWSER_CRASH = "browser_crash"
    UNKNOWN = "unknown"


@dataclass
class InputElement:
    """Represents a text input, textarea, or similar element."""

    selector: str
    tag: str
    input_type: str | None = None
    id: str | None = None
    name: str | None = None
    placeholder: str | None = None
    label_text: str | None = None
    nearby_text: str | None = None
    current_value: str = ""
    is_visible: bool = True
    is_enabled: bool = True
    is_required: bool = False
    pattern: str | None = None
    maxlength: int | None = None
    autocomplete: str | None = None
    relevance_score: float = 0.0


@dataclass
class ButtonElement:
    """Represents a clickable button or link."""

    selector: str
    tag: str
    text: str
    id: str | None = None
    type: str | None = None
    is_visible: bool = True
    is_enabled: bool = True
    is_primary: bool = False
    relevance_score: float = 0.0


@dataclass
class LinkElement:
    """Represents a navigation link (<a> tag)."""

    selector: str
    href: str
    text: str
    id: str | None = None
    is_visible: bool = True
    relevance_score: float = 0.0


@dataclass
class SelectOption:
    """Represents an option in a dropdown."""

    value: str
    text: str
    is_placeholder: bool = False


@dataclass
class SelectElement:
    """Represents a native select dropdown."""

    selector: str
    options: list[SelectOption]
    id: str | None = None
    name: str | None = None
    label_text: str | None = None
    selected_value: str | None = None
    is_visible: bool = True
    is_enabled: bool = True
    looks_like_address_list: bool = False


@dataclass
class CustomDropdown:
    """Represents a custom (non-native) dropdown."""

    trigger_selector: str
    options: list[str]
    container_selector: str | None = None
    is_open: bool = False
    looks_like_address_list: bool = False


@dataclass
class Observation:
    """Structured snapshot of the current page state."""

    url: str
    page_title: str
    timestamp: datetime
    inputs: list[InputElement]
    buttons: list[ButtonElement]
    links: list[LinkElement]
    selects: list[SelectElement]
    custom_dropdowns: list[CustomDropdown]
    visible_text_sample: str
    contains_error_message: bool = False
    error_message_text: str | None = None
    contains_success_indicators: bool = False
    success_indicator_text: str | None = None
    new_elements_since_last: list[str] = field(default_factory=list)

    @property
    def hash(self) -> str:
        """Compute hash for loop detection."""
        # Use more text to avoid collision, include input/button identifiers
        key_data = {
            "url": self.url,
            "text_sample": self.visible_text_sample[:500],  # More text for uniqueness
            "num_inputs": len(self.inputs),
            "num_buttons": len(self.buttons),
            "num_selects": len(self.selects),
            # Include selector fingerprint for better uniqueness
            "input_selectors": sorted([inp.selector for inp in self.inputs[:5]]),
            "button_selectors": sorted([btn.selector for btn in self.buttons[:5]]),
        }
        return hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()


@dataclass
class Action:
    """Represents a single action to perform on the page."""

    action_type: Literal["fill", "click", "select", "wait"]
    selector: str
    value: str | None = None
    description: str = ""
    confidence: float = 0.0


@dataclass
class ExecutionResult:
    """Result of executing an action."""

    success: bool
    action: Action
    error_type: str | None = None
    error_message: str | None = None
    screenshot_path: str | None = None
    duration_ms: int = 0


@dataclass
class HistoryEntry:
    """A single entry in the action history."""

    observation: Observation
    action: Action
    result: ExecutionResult


@dataclass
class NetworkEntry:
    """Captured network request/response."""

    timestamp: datetime
    request_url: str
    request_method: str
    request_headers: dict[str, str]
    request_body: str | None
    response_status: int | None
    response_headers: dict[str, str] | None
    response_body: str | None
    duration_ms: int
    resource_type: str


@dataclass
class SessionResult:
    """Result of a session exploration attempt."""

    status: Literal["success", "failure"]
    council_id: str
    final_url: str
    iterations: int
    history: list[HistoryEntry]
    failure_category: FailureCategory | None = None
    failure_detail: str | None = None
    is_recoverable: bool = True
    error_screenshots: list[str] = field(default_factory=list)
    detected_blockers: list[str] = field(default_factory=list)


@dataclass
class TestData:
    """Test data for a council exploration session."""

    test_postcode: str
    test_address: str | None = None


@dataclass
class Council:
    """Represents a UK council."""

    council_id: str
    name: str
    url: str
    test_postcode: str
    test_address: str | None = None

    def get_test_data(self) -> TestData:
        """Get TestData from Council."""
        return TestData(
            test_postcode=self.test_postcode,
            test_address=self.test_address,
        )


@dataclass
class PreflightResult:
    """Result of pre-flight validation for a council."""

    council_id: str
    url_reachable: bool
    http_status: int | None
    postcode_valid: bool
    detected_issues: list[str]
    skip_reason: str | None = None


@dataclass
class Config:
    """Global configuration for the scraper."""

    # Timeouts (ms)
    page_load_timeout_ms: int = 30000
    element_timeout_ms: int = 5000
    click_timeout_ms: int = 5000
    settle_timeout_ms: int = 10000

    # Delays (ms)
    typing_delay_ms: int = 50
    action_delay_ms: int = 500
    settle_check_interval_ms: int = 100
    inter_council_delay_ms: int = 2000  # Delay between councils to avoid rate limiting

    # Limits
    max_iterations: int = 50
    max_same_url_visits: int = 3
    max_action_retries: int = 2

    # Settle detection (ms)
    network_idle_threshold_ms: int = 500
    dom_stable_threshold_ms: int = 500

    # Recording
    screenshot_on_action: bool = True
    screenshot_on_success: bool = True
    screenshot_on_failure: bool = True

    # Browser
    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720


@dataclass
class RunnerResult:
    """Overall result from running all councils."""

    success_count: int
    failure_count: int
    skipped_count: int
    results: list[SessionResult]
