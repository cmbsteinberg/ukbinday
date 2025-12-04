# UK Council Bin Collection Scraper

## Technical Specification

**Version:** 1.1  
**Target:** Python 3.11+ with Playwright  
**Scope:** Automated exploration of 350 UK council websites to identify bin collection lookup flows and capture underlying API calls

**Changelog:**
- v1.1: Added cookie consent handling, incremental recording, rich error taxonomy, pre-flight validation, expanded keyword matching

---

## 1. Problem Statement

UK councils each have their own websites for residents to check bin collection dates. These sites vary enormously in implementation: some use simple form submissions, others require JavaScript-heavy interactions, address lookups via dropdowns or autocomplete, and multi-page flows. The goal is to programmatically navigate these sites using a test postcode, triggering and recording the network requests that reveal the underlying APIs.

This specification covers the **browser automation and form interaction layer**. A separate effort will handle API reverse engineering from the captured network traffic.

---

## 2. Design Principles

### 2.1 Exploration Over Precision

The system explores unknown territory. It should try multiple approaches, tolerate failures gracefully, and prioritise coverage over elegance. It's acceptable to click the wrong button occasionally if the system eventually finds the right path.

### 2.2 Observability

Every action, observation, and network request must be recorded. When something fails, there should be enough information to understand why. When something succeeds, there should be enough information to extract the API pattern.

### 2.3 Stateless Components

Individual components (Observer, Strategist, Executor) should be stateless or minimally stateful. Session state lives in a dedicated place, making the system easier to reason about and debug.

### 2.4 Graceful Degradation

The system should handle 80-90% of councils automatically. The remaining edge cases should fail cleanly with good diagnostics, allowing either configuration-based fixes or manual intervention.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                           Runner                                 │
│  - Loads council list                                           │
│  - Iterates through councils                                    │
│  - Manages browser lifecycle                                    │
│  - Aggregates results                                           │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                          Session                                 │
│  - Owns Playwright page instance                                │
│  - Owns Recorder instance                                       │
│  - Maintains action history                                     │
│  - Runs main exploration loop                                   │
│  - Detects termination conditions                               │
└─────────────────────────────────────────────────────────────────┘
                                │
            ┌───────────────────┼───────────────────┐
            ▼                   ▼                   ▼
┌───────────────────┐ ┌─────────────────┐ ┌─────────────────────┐
│     Observer      │ │   Strategist    │ │      Executor       │
│                   │ │                 │ │                     │
│ - Snapshots page  │ │ - Ranks actions │ │ - Performs actions  │
│ - Finds inputs    │ │ - Applies rules │ │ - Handles waits     │
│ - Finds buttons   │ │ - Filters tried │ │ - Returns results   │
│ - Detects success │ │                 │ │                     │
└───────────────────┘ └─────────────────┘ └─────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                          Recorder                                │
│  - Captures network requests/responses                          │
│  - Takes screenshots                                            │
│  - Logs action sequences                                        │
│  - Writes to disk incrementally                                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Configuration                             │
│  - Global settings (timeouts, delays)                           │
│  - Per-council overrides                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Component Specifications

### 4.1 Runner

**Responsibility:** Orchestrate the overall process across all councils.

**Input:**
- Path to council list (JSON or CSV)
- Global configuration
- Output directory

**Council List Format:**
```json
[
  {
    "council_id": "birmingham",
    "name": "Birmingham City Council",
    "url": "https://www.birmingham.gov.uk/bin-collection",
    "test_postcode": "B1 1AA",
    "test_address": "1 Example Street"  // optional, for full address sites
  }
]
```

**Behaviour:**
1. Load council list
2. Load existing results to determine what's already processed (for resumability)
3. **Run pre-flight validation** (see below)
4. For each unprocessed council:
   - Create a new browser context
   - Create a Session
   - Run the session
   - Record the outcome
   - Close the browser context
5. Generate summary report

**Pre-flight Validation:**

Before running the full exploration, validate each council entry:

```python
@dataclass
class PreflightResult:
    council_id: str
    url_reachable: bool
    http_status: int | None
    postcode_valid: bool
    detected_issues: list[str]  # e.g., ["captcha_detected", "login_required"]
    skip_reason: str | None     # If we should skip, why

async def preflight_check(council: Council) -> PreflightResult:
    """Quick validation before full exploration."""
    issues = []
    
    # 1. Validate postcode format
    postcode_valid = bool(re.match(
        r'^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$',
        council.test_postcode.upper()
    ))
    if not postcode_valid:
        issues.append("invalid_postcode_format")
    
    # 2. Check URL is reachable
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(council.url, timeout=10) as resp:
                http_status = resp.status
                url_reachable = resp.status < 400
    except:
        http_status = None
        url_reachable = False
        issues.append("url_unreachable")
    
    # 3. Quick page load to detect blockers (optional, can be disabled)
    # This catches CAPTCHAs, login walls, etc. early
    
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
```

Pre-flight runs before the main loop and produces a report of councils that will be skipped, allowing early detection of bad data.

**Output:**
- Per-council result directories containing recordings
- Summary JSON with success/failure counts and categories

**Error Handling:**
- If a session crashes, log the error and continue to the next council
- If the browser crashes, attempt to restart it
- If too many consecutive failures occur, pause and alert

**Code Structure:**
```python
# runner.py

class Runner:
    def __init__(self, council_list_path: str, output_dir: str, config: Config):
        ...
    
    async def run(self) -> RunnerResult:
        """Process all councils, return aggregate results."""
        ...
    
    async def run_single(self, council: Council) -> SessionResult:
        """Process a single council. Useful for testing."""
        ...
    
    def _load_councils(self) -> list[Council]:
        ...
    
    def _load_existing_results(self) -> set[str]:
        """Return council IDs already processed."""
        ...
    
    def _generate_report(self, results: list[SessionResult]) -> None:
        ...
```

---

### 4.2 Session

**Responsibility:** Manage a single exploration attempt for one council.

**State:**
- Playwright Page instance
- Recorder instance
- Action history: list of (observation, action, result) tuples
- Current phase (for debugging): "initial", "postcode_entry", "address_selection", "result_extraction"
- Test data for this council

**Main Loop:**
```python
async def run(self) -> SessionResult:
    await self._navigate_to_start_url()
    
    for iteration in range(self.config.max_iterations):
        # 1. Observe current state
        observation = await self.observer.observe(self.page)
        
        # 2. Record the observation
        self.recorder.record_observation(observation)
        
        # 3. Check termination conditions
        if self._is_success(observation):
            return SessionResult(status="success", ...)
        
        if self._is_dead_end(observation):
            return SessionResult(status="dead_end", ...)
        
        if self._is_loop(observation):
            return SessionResult(status="loop_detected", ...)
        
        # 4. Get candidate actions
        candidates = self.strategist.get_actions(observation, self.history)
        
        if not candidates:
            return SessionResult(status="no_actions_available", ...)
        
        # 5. Execute top action
        action = candidates[0]
        result = await self.executor.execute(self.page, action)
        
        # 6. Record the action
        self.history.append((observation, action, result))
        self.recorder.record_action(action, result)
        
        # 7. Wait for page to settle
        await self._wait_for_settle()
    
    return SessionResult(status="max_iterations_exceeded", ...)
```

**Termination Detection:**

*Success indicators:*
- Page contains keywords: "next collection", "bin day", "collection date", "recycling", "waste collection"
- Page contains dates in common formats (especially dates in the near future)
- URL contains success-indicating paths: "/results", "/collection-dates", "/your-bins"

*Dead end indicators:*
- Error messages visible: "postcode not found", "invalid address", "no results"
- Page is empty or shows a generic error page
- Page requires login or registration

*Loop detection:*
- Same observation hash seen multiple times
- Same URL visited more than N times
- Same action attempted more than N times with no state change

**Code Structure:**
```python
# session.py

class FailureCategory(Enum):
    """Categorise failures for better diagnostics and retry decisions."""
    
    # Recoverable - might work with different approach or retry
    TIMEOUT = "timeout"                    # Page or element took too long
    ELEMENT_NOT_FOUND = "element_not_found"  # Expected element missing
    LOOP_DETECTED = "loop_detected"        # Stuck in a cycle
    NO_ACTIONS = "no_actions"              # Strategist has no ideas
    MAX_ITERATIONS = "max_iterations"      # Hit iteration limit
    
    # Likely data issues - check council config
    POSTCODE_NOT_FOUND = "postcode_not_found"   # Site says postcode invalid
    ADDRESS_NOT_FOUND = "address_not_found"     # No addresses for postcode
    INVALID_INPUT = "invalid_input"             # Form validation failed
    
    # Fundamental blockers - need manual intervention
    CAPTCHA_PRESENT = "captcha_present"    # CAPTCHA blocking progress
    LOGIN_REQUIRED = "login_required"      # Site requires authentication
    PAGE_NOT_FOUND = "page_not_found"      # 404 or similar
    SITE_ERROR = "site_error"              # 500 or site-side error
    
    # Infrastructure issues
    NETWORK_ERROR = "network_error"        # Connection failed
    BROWSER_CRASH = "browser_crash"        # Playwright crashed
    UNKNOWN = "unknown"                    # Catch-all

@dataclass
class SessionResult:
    status: Literal["success", "failure"]
    council_id: str
    final_url: str
    iterations: int
    history: list[HistoryEntry]
    
    # Rich error information
    failure_category: FailureCategory | None = None
    failure_detail: str | None = None
    is_recoverable: bool = True            # Hint for retry logic
    
    # Diagnostic info
    error_screenshots: list[str] = field(default_factory=list)
    detected_blockers: list[str] = field(default_factory=list)  # ["captcha", "login_wall"]

def _classify_failure(
    observation: Observation,
    last_action: Action | None,
    last_result: ExecutionResult | None,
    error: Exception | None,
) -> tuple[FailureCategory, str, bool]:
    """Determine failure category from available evidence."""
    
    # Check for known blockers in page content
    page_text = observation.visible_text_sample.lower()
    
    if any(phrase in page_text for phrase in ["captcha", "robot", "verify you're human"]):
        return FailureCategory.CAPTCHA_PRESENT, "CAPTCHA detected on page", False
    
    if any(phrase in page_text for phrase in ["sign in", "log in", "login required"]):
        return FailureCategory.LOGIN_REQUIRED, "Login wall detected", False
    
    if any(phrase in page_text for phrase in ["postcode not found", "invalid postcode", "not recognised"]):
        return FailureCategory.POSTCODE_NOT_FOUND, "Site rejected the test postcode", True
    
    if any(phrase in page_text for phrase in ["no addresses", "address not found"]):
        return FailureCategory.ADDRESS_NOT_FOUND, "No addresses found for postcode", True
    
    # Check HTTP-level errors
    if "404" in page_text or observation.url.endswith("/404"):
        return FailureCategory.PAGE_NOT_FOUND, "Page not found (404)", False
    
    # Check last action result
    if last_result and not last_result.success:
        if last_result.error_type == "timeout":
            return FailureCategory.TIMEOUT, f"Timeout on {last_action.description}", True
        if last_result.error_type == "element_not_found":
            return FailureCategory.ELEMENT_NOT_FOUND, f"Element not found: {last_action.selector}", True
    
    # Check for exceptions
    if error:
        error_str = str(error).lower()
        if "net::" in error_str or "connection" in error_str:
            return FailureCategory.NETWORK_ERROR, str(error), True
        if "crash" in error_str or "target closed" in error_str:
            return FailureCategory.BROWSER_CRASH, str(error), True
    
    return FailureCategory.UNKNOWN, "Could not determine failure reason", True

class Session:
    def __init__(
        self,
        page: Page,
        council: Council,
        config: Config,
        recorder: Recorder,
        observer: Observer,
        strategist: Strategist,
        executor: Executor,
    ):
        ...
    
    async def run(self) -> SessionResult:
        ...
    
    def _is_success(self, observation: Observation) -> bool:
        ...
    
    def _is_dead_end(self, observation: Observation) -> bool:
        ...
    
    def _is_loop(self, observation: Observation) -> bool:
        ...
    
    async def _wait_for_settle(self) -> None:
        ...
```

---

### 4.3 Observer

**Responsibility:** Create a structured snapshot of the current page state.

**Design:** Pure function with no side effects. Given a page, returns an Observation.

**Observation Data Structure:**
```python
@dataclass
class InputElement:
    selector: str                    # CSS selector to locate this element
    tag: str                         # "input", "textarea"
    input_type: str | None           # "text", "search", "tel", etc.
    id: str | None
    name: str | None
    placeholder: str | None
    label_text: str | None           # Text from associated <label>
    nearby_text: str | None          # Text in proximity (parent, siblings)
    current_value: str
    is_visible: bool
    is_enabled: bool
    is_required: bool
    pattern: str | None              # HTML5 validation pattern
    maxlength: int | None
    autocomplete: str | None
    relevance_score: float           # How likely this is a postcode/address field

@dataclass
class ButtonElement:
    selector: str
    tag: str                         # "button", "input[type=submit]", "a"
    text: str
    id: str | None
    type: str | None                 # "submit", "button"
    is_visible: bool
    is_enabled: bool
    is_primary: bool                 # Appears to be the main action button
    relevance_score: float           # How likely this is a submit/search button

@dataclass
class SelectElement:
    selector: str
    id: str | None
    name: str | None
    label_text: str | None
    options: list[SelectOption]      # Value and text for each option
    selected_value: str | None
    is_visible: bool
    is_enabled: bool
    looks_like_address_list: bool    # Options appear to be addresses

@dataclass
class SelectOption:
    value: str
    text: str
    is_placeholder: bool             # e.g., "Select an address..."

@dataclass
class CustomDropdown:
    trigger_selector: str            # Element to click to open
    container_selector: str | None   # Container for options (if detectable)
    options: list[str]               # Visible option texts
    is_open: bool
    looks_like_address_list: bool

@dataclass
class Observation:
    url: str
    page_title: str
    timestamp: datetime
    
    inputs: list[InputElement]
    buttons: list[ButtonElement]
    selects: list[SelectElement]
    custom_dropdowns: list[CustomDropdown]
    
    visible_text_sample: str         # First N characters of visible text
    contains_error_message: bool
    error_message_text: str | None
    contains_success_indicators: bool
    success_indicator_text: str | None
    
    new_elements_since_last: list[str]  # Selectors of elements that appeared
    
    hash: str                        # For loop detection
```

**Relevance Scoring:**

For inputs, score based on:
- Label/placeholder contains postcode terms: +0.5
  - Terms: "postcode", "post code", "postal code", "zip", "zip code", "your postcode", "enter postcode"
- Label/placeholder contains address terms: +0.3
  - Terms: "address", "house", "street", "property", "building", "flat", "apartment", "dwelling", "premises"
- Name/id contains relevant terms: +0.3
  - Terms: "postcode", "postal", "address", "uprn", "property"
- Has UK postcode pattern validation: +0.4
- Maxlength is 7-10 (UK postcode length): +0.2
- Is currently empty: +0.1
- Is the only visible text input on page: +0.2

For buttons, score based on:
- Text contains search terms: +0.4
  - Terms: "find", "search", "look up", "lookup", "submit", "go", "check", "get"
- Text contains navigation terms: +0.3
  - Terms: "next", "continue", "proceed", "confirm"
- Text contains bin-specific terms: +0.3
  - Terms: "find my bin", "collection", "bin day", "check bins"
- Is type="submit": +0.2
- Has primary styling (check for common CSS classes): +0.2
  - Classes: "btn-primary", "primary", "main", "cta", "submit"
- Is near a high-relevance input: +0.2

**Detecting Custom Dropdowns:**

Look for:
- Elements with role="combobox" or role="listbox"
- Elements with aria-haspopup="listbox"
- Elements with common class names: "dropdown", "select", "autocomplete"
- Input elements with associated suggestion containers

**Implementation Notes:**
```python
# observer.py

class Observer:
    def __init__(self, config: Config):
        self.config = config
        self._previous_element_selectors: set[str] = set()
    
    async def observe(self, page: Page) -> Observation:
        """Create a snapshot of the current page state."""
        ...
    
    async def _find_inputs(self, page: Page) -> list[InputElement]:
        ...
    
    async def _find_buttons(self, page: Page) -> list[ButtonElement]:
        ...
    
    async def _find_selects(self, page: Page) -> list[SelectElement]:
        ...
    
    async def _find_custom_dropdowns(self, page: Page) -> list[CustomDropdown]:
        ...
    
    async def _get_label_for_element(self, page: Page, element) -> str | None:
        """Find label text via for attribute, aria-label, or proximity."""
        ...
    
    async def _get_nearby_text(self, page: Page, element) -> str | None:
        """Get text from parent and sibling elements."""
        ...
    
    def _score_input_relevance(self, input_el: InputElement) -> float:
        ...
    
    def _score_button_relevance(self, button: ButtonElement) -> float:
        ...
    
    def _detect_success_indicators(self, page_text: str) -> tuple[bool, str | None]:
        ...
    
    def _detect_error_indicators(self, page_text: str) -> tuple[bool, str | None]:
        ...
    
    def _compute_hash(self, observation: Observation) -> str:
        """Hash key fields for loop detection."""
        ...
```

---

### 4.4 Strategist

**Responsibility:** Given an observation and history, return a prioritised list of candidate actions.

**Action Data Structure:**
```python
@dataclass
class Action:
    action_type: Literal["fill", "click", "select", "wait"]
    selector: str
    value: str | None = None         # For fill and select actions
    description: str = ""            # Human-readable description
    confidence: float = 0.0          # How confident we are this is the right action

@dataclass 
class ActionSequence:
    """A group of actions that should be executed together."""
    actions: list[Action]
    description: str
    confidence: float
```

**Rule Engine:**

The Strategist applies rules in priority order. Each rule examines the observation and proposes zero or more actions.

```python
class Rule(ABC):
    @abstractmethod
    def propose(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Return proposed actions, possibly empty."""
        ...
    
    @property
    @abstractmethod
    def priority(self) -> int:
        """Lower numbers = higher priority."""
        ...
```

**Core Rules:**

0. **DismissCookieConsentRule** (priority: 1)
   - Condition: Page contains a cookie consent banner/modal
   - Detection: Look for elements matching common patterns:
     - Buttons with text: "accept", "agree", "ok", "got it", "allow", "consent", "accept all", "allow all"
     - Near text containing: "cookie", "privacy", "gdpr", "consent"
     - Common class names: "cookie-banner", "consent-modal", "gdpr-popup", "cookie-notice"
     - Common IDs: "cookie-consent", "gdpr-banner", "privacy-notice"
   - Action: Click the accept/dismiss button
   - Confidence: High if clear cookie-related context, medium otherwise
   - Note: This rule should fire early and repeatedly until no banner is detected

1. **FillPostcodeRule** (priority: 10)
   - Condition: There's a high-relevance input that's empty
   - Action: Fill with test postcode
   - Confidence: Based on input's relevance score

2. **ClickSubmitAfterFillRule** (priority: 20)
   - Condition: We just filled an input, and there's a submit-looking button
   - Action: Click the button
   - Confidence: Based on button's relevance score and proximity to filled input

3. **SelectAddressRule** (priority: 30)
   - Condition: There's a select element with address-looking options
   - Action: Select the first non-placeholder option
   - Confidence: High if options clearly look like addresses

4. **SelectFromCustomDropdownRule** (priority: 35)
   - Condition: There's a custom dropdown with address-looking options
   - Action: Click an option
   - Confidence: Based on how certain we are it's an address dropdown

5. **OpenCustomDropdownRule** (priority: 40)
   - Condition: There's a closed custom dropdown that might contain addresses
   - Action: Click to open it
   - Confidence: Medium

6. **ClickContinueButtonRule** (priority: 50)
   - Condition: We've selected an address, there's a "continue" or "next" button
   - Action: Click it
   - Confidence: High if we're in address-selected state

7. **ExploratoryClickRule** (priority: 100)
   - Condition: Nothing else matches, there are unclicked buttons
   - Action: Click them in order of relevance
   - Confidence: Low

**Filtering Already-Tried Actions:**

Before returning actions, filter out:
- Actions with the same (type, selector, value) that appear in recent history
- Exception: click actions can be retried if page state has changed significantly

**Implementation Notes:**
```python
# strategist.py

class Strategist:
    def __init__(self, config: Config, rules: list[Rule] | None = None):
        self.config = config
        self.rules = rules or self._default_rules()
    
    def get_actions(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Return prioritised list of candidate actions."""
        all_candidates = []
        
        for rule in sorted(self.rules, key=lambda r: r.priority):
            candidates = rule.propose(observation, history, test_data)
            all_candidates.extend(candidates)
        
        # Filter already-tried actions
        filtered = self._filter_tried(all_candidates, history, observation)
        
        # Sort by confidence descending
        filtered.sort(key=lambda a: a.confidence, reverse=True)
        
        return filtered
    
    def _filter_tried(
        self,
        candidates: list[Action],
        history: list[HistoryEntry],
        observation: Observation,
    ) -> list[Action]:
        ...
    
    def _default_rules(self) -> list[Rule]:
        return [
            DismissCookieConsentRule(),  # Must run first
            FillPostcodeRule(),
            ClickSubmitAfterFillRule(),
            SelectAddressRule(),
            SelectFromCustomDropdownRule(),
            OpenCustomDropdownRule(),
            ClickContinueButtonRule(),
            ExploratoryClickRule(),
        ]
```

---

### 4.5 Executor

**Responsibility:** Perform actions on the page reliably.

**Design Principles:**
- Handle common edge cases (element not visible, element not enabled, click intercepted)
- Never leave the page in an uncertain state
- Return structured results including success/failure and diagnostics

**Execution Result:**
```python
@dataclass
class ExecutionResult:
    success: bool
    action: Action
    error_type: str | None = None    # "element_not_found", "timeout", "intercepted", etc.
    error_message: str | None = None
    screenshot_path: str | None = None
    duration_ms: int = 0
```

**Action Handlers:**

```python
# executor.py

class Executor:
    def __init__(self, config: Config):
        self.config = config
    
    async def execute(self, page: Page, action: Action) -> ExecutionResult:
        """Execute an action on the page."""
        try:
            if action.action_type == "fill":
                return await self._execute_fill(page, action)
            elif action.action_type == "click":
                return await self._execute_click(page, action)
            elif action.action_type == "select":
                return await self._execute_select(page, action)
            elif action.action_type == "wait":
                return await self._execute_wait(page, action)
            else:
                return ExecutionResult(
                    success=False,
                    action=action,
                    error_type="unknown_action_type",
                )
        except Exception as e:
            return ExecutionResult(
                success=False,
                action=action,
                error_type="exception",
                error_message=str(e),
            )
    
    async def _execute_fill(self, page: Page, action: Action) -> ExecutionResult:
        """Fill a text input."""
        try:
            element = page.locator(action.selector)
            
            # Ensure element is ready
            await element.wait_for(state="visible", timeout=self.config.element_timeout_ms)
            
            # Scroll into view
            await element.scroll_into_view_if_needed()
            
            # Clear existing value and type new value
            await element.clear()
            await element.type(action.value, delay=self.config.typing_delay_ms)
            
            return ExecutionResult(success=True, action=action)
        
        except TimeoutError:
            return ExecutionResult(
                success=False,
                action=action,
                error_type="timeout",
                error_message=f"Element {action.selector} not visible within timeout",
            )
    
    async def _execute_click(self, page: Page, action: Action) -> ExecutionResult:
        """Click an element."""
        try:
            element = page.locator(action.selector)
            
            await element.wait_for(state="visible", timeout=self.config.element_timeout_ms)
            await element.scroll_into_view_if_needed()
            
            # Use force=False to ensure element is actually clickable
            await element.click(timeout=self.config.click_timeout_ms)
            
            return ExecutionResult(success=True, action=action)
        
        except TimeoutError:
            return ExecutionResult(
                success=False,
                action=action,
                error_type="timeout",
            )
    
    async def _execute_select(self, page: Page, action: Action) -> ExecutionResult:
        """Select an option from a dropdown."""
        try:
            element = page.locator(action.selector)
            await element.wait_for(state="visible", timeout=self.config.element_timeout_ms)
            
            # Try selecting by value first, then by label
            try:
                await element.select_option(value=action.value)
            except:
                await element.select_option(label=action.value)
            
            return ExecutionResult(success=True, action=action)
        
        except TimeoutError:
            return ExecutionResult(
                success=False,
                action=action,
                error_type="timeout",
            )
    
    async def _execute_wait(self, page: Page, action: Action) -> ExecutionResult:
        """Explicit wait, used sparingly."""
        await page.wait_for_timeout(int(action.value))
        return ExecutionResult(success=True, action=action)
```

---

### 4.6 Recorder

**Responsibility:** Capture all activity for later analysis.

**Design Principles:**
- **Stream incrementally**: Write to disk as events occur, not at session end. This ensures data survives crashes.
- **Record everything**: Capture all network requests; filter during analysis, not capture. Disk is cheap; missing data is expensive.
- **Use append-friendly formats**: JSONL (JSON Lines) allows appending without loading entire files.

**What to Record:**
- Network requests and responses (the primary output for API reverse engineering)
- Screenshots at key moments
- Action sequence with observations
- Timing information

**Network Recording:**

```python
@dataclass
class NetworkEntry:
    timestamp: datetime
    request_url: str
    request_method: str
    request_headers: dict[str, str]
    request_body: str | None
    response_status: int | None
    response_headers: dict[str, str] | None
    response_body: str | None
    duration_ms: int
    resource_type: str              # "document", "xhr", "fetch", "script", etc.
```

**Recording Strategy:**

Record ALL network requests. Do not filter during capture - this avoids missing:
- APIs loaded via script tags
- GraphQL endpoints without obvious URL patterns  
- JSONP callbacks
- Interesting data in unexpected resource types

Filtering happens during analysis, not capture. The Recorder's job is to be comprehensive.

**Implementation:**
```python
# recorder.py

class Recorder:
    def __init__(self, output_dir: str, council_id: str, config: Config):
        self.output_dir = Path(output_dir) / council_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        
        # Open file handles for streaming writes
        self._network_file = open(self.output_dir / "network.jsonl", "a")
        self._action_file = open(self.output_dir / "actions.jsonl", "a")
        self._observation_file = open(self.output_dir / "observations.jsonl", "a")
        
        # Track pending requests (waiting for response)
        self._pending_requests: dict[str, NetworkEntry] = {}
    
    def setup_network_capture(self, page: Page) -> None:
        """Attach network event handlers to the page."""
        page.on("request", self._on_request)
        page.on("response", self._on_response)
    
    def _on_request(self, request: Request) -> None:
        """Handle outgoing request - record ALL requests."""
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
        # Use URL + timestamp as key to handle parallel requests to same URL
        key = f"{request.url}:{entry.timestamp.timestamp()}"
        self._pending_requests[key] = entry
    
    async def _on_response(self, response: Response) -> None:
        """Handle incoming response."""
        # Find matching request
        url = response.url
        matching_key = None
        for key in self._pending_requests:
            if key.startswith(url + ":"):
                matching_key = key
                break
        
        if matching_key:
            entry = self._pending_requests.pop(matching_key)
            entry.response_status = response.status
            entry.response_headers = dict(response.headers)
            entry.duration_ms = int((datetime.now() - entry.timestamp).total_seconds() * 1000)
            
            # Capture response body for text-based content types
            content_type = response.headers.get("content-type", "")
            if any(t in content_type for t in ["json", "xml", "html", "text", "javascript"]):
                try:
                    entry.response_body = await response.text()
                except:
                    entry.response_body = None
            
            # Stream to disk immediately
            self._write_network_entry(entry)
    
    def _write_network_entry(self, entry: NetworkEntry) -> None:
        """Append a network entry to the JSONL file."""
        self._network_file.write(json.dumps(asdict(entry), default=str) + "\n")
        self._network_file.flush()  # Ensure it's written
    
    def record_observation(self, observation: Observation) -> None:
        """Log an observation - streams to disk immediately."""
        self._observation_file.write(json.dumps(asdict(observation), default=str) + "\n")
        self._observation_file.flush()
    
    def record_action(self, action: Action, result: ExecutionResult) -> None:
        """Log an action and its result - streams to disk immediately."""
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
        await page.screenshot(path=path, full_page=True)
        return str(path)
    
    def close(self) -> None:
        """Close file handles. Call this when session ends."""
        self._network_file.close()
        self._action_file.close()
        self._observation_file.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
```

**Output Format:**

Files use JSONL (JSON Lines) format - one JSON object per line. This allows:
- Appending without loading the whole file
- Streaming reads during analysis
- Partial file recovery if process crashes mid-write

```bash
# Example: Read network log incrementally
while read -r line; do
    echo "$line" | jq '.request_url'
done < output/birmingham/network.jsonl

# Example: Filter to XHR requests during analysis
jq -c 'select(.resource_type == "xhr")' output/birmingham/network.jsonl
```

---

### 4.7 Configuration

**Global Configuration:**
```python
@dataclass
class Config:
    # Timeouts
    page_load_timeout_ms: int = 30000
    element_timeout_ms: int = 5000
    click_timeout_ms: int = 5000
    settle_timeout_ms: int = 10000
    
    # Delays
    typing_delay_ms: int = 50        # Delay between keystrokes
    action_delay_ms: int = 500       # Delay after each action
    settle_check_interval_ms: int = 100
    
    # Limits
    max_iterations: int = 50
    max_same_url_visits: int = 3
    max_action_retries: int = 2
    
    # Settle detection
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
```

**Per-Council Overrides:**
```python
@dataclass
class CouncilOverride:
    council_id: str
    
    # Selector hints
    postcode_input_selector: str | None = None
    submit_button_selector: str | None = None
    address_dropdown_selector: str | None = None
    
    # Timing overrides
    extra_wait_after_submit_ms: int | None = None
    typing_delay_ms: int | None = None
    
    # Flow hints
    requires_house_number: bool = False
    has_captcha: bool = False
    skip: bool = False              # Skip this council entirely
    notes: str = ""                 # Human notes about this council
```

**Loading Configuration:**
```python
# config.py

def load_config(path: str | None = None) -> Config:
    """Load global configuration from file or use defaults."""
    if path and Path(path).exists():
        with open(path) as f:
            data = json.load(f)
        return Config(**data)
    return Config()

def load_overrides(path: str) -> dict[str, CouncilOverride]:
    """Load per-council overrides from file."""
    if not Path(path).exists():
        return {}
    
    with open(path) as f:
        data = json.load(f)
    
    return {
        item["council_id"]: CouncilOverride(**item)
        for item in data
    }
```

---

## 5. Playwright Best Practices

### 5.1 Browser Context Management

Always use browser contexts rather than pages directly for isolation:

```python
async def process_council(browser: Browser, council: Council) -> SessionResult:
    # Each council gets a fresh context - no shared cookies or state
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent="Mozilla/5.0 ...",  # Use a realistic user agent
    )
    
    try:
        page = await context.new_page()
        # ... run session
    finally:
        await context.close()  # Always clean up
```

### 5.2 Waiting Strategies

**Never use arbitrary sleeps.** Always wait for specific conditions:

```python
# Bad - arbitrary wait
await page.wait_for_timeout(2000)

# Good - wait for specific condition
await page.wait_for_selector(".results-container", state="visible")

# Good - wait for network to settle
await page.wait_for_load_state("networkidle")

# Good - wait for function to return true
await page.wait_for_function("document.querySelector('.loading') === null")
```

**Combine waiting strategies for reliability:**

```python
async def wait_for_settle(page: Page, config: Config) -> None:
    """Wait for page to be stable enough to observe."""
    try:
        # Wait for network idle with timeout
        await page.wait_for_load_state("networkidle", timeout=config.settle_timeout_ms)
    except TimeoutError:
        # Network didn't idle, but that's okay for some sites
        pass
    
    # Additional short wait for any final DOM updates
    await page.wait_for_timeout(config.settle_check_interval_ms)
```

### 5.3 Robust Element Selection

**Prefer multiple selector strategies:**

```python
async def find_postcode_input(page: Page) -> str | None:
    """Try multiple strategies to find the postcode input."""
    strategies = [
        # By label
        "input[id]:has(+ label:text-matches('postcode', 'i'))",
        "label:text-matches('postcode', 'i') + input",
        
        # By placeholder
        "input[placeholder*='postcode' i]",
        "input[placeholder*='post code' i]",
        
        # By name/id
        "input[name*='postcode' i]",
        "input[id*='postcode' i]",
        
        # By pattern (UK postcode regex)
        "input[pattern*='[A-Z]']",
    ]
    
    for selector in strategies:
        try:
            element = page.locator(selector).first
            if await element.is_visible():
                return selector
        except:
            continue
    
    return None
```

### 5.4 Handling Dynamic Content

**Wait for elements to appear after actions:**

```python
async def click_and_wait_for_change(
    page: Page,
    click_selector: str,
    expected_selector: str,
    timeout_ms: int = 5000,
) -> bool:
    """Click something and wait for expected change."""
    # Record current state
    had_element = await page.locator(expected_selector).count() > 0
    
    # Perform click
    await page.click(click_selector)
    
    # Wait for the expected element to appear (or change)
    try:
        await page.wait_for_selector(expected_selector, state="visible", timeout=timeout_ms)
        return True
    except TimeoutError:
        return False
```

### 5.5 Handling Native Selects vs Custom Dropdowns

**Native `<select>` elements:**
```python
# Select by value
await page.select_option("select#address", value="12345")

# Select by visible text
await page.select_option("select#address", label="1 High Street, London")

# Select by index
await page.select_option("select#address", index=1)
```

**Custom dropdowns (div-based):**
```python
async def select_from_custom_dropdown(
    page: Page,
    trigger_selector: str,
    option_text: str,
) -> bool:
    """Handle non-native dropdown."""
    # Click to open
    await page.click(trigger_selector)
    
    # Wait for options to appear
    await page.wait_for_selector("[role='option'], .dropdown-item", state="visible")
    
    # Find and click the desired option
    option = page.locator(f"text='{option_text}'").first
    await option.click()
    
    return True
```

### 5.6 Error Handling Patterns

**Wrap all Playwright operations:**

```python
async def safe_click(page: Page, selector: str) -> tuple[bool, str | None]:
    """Click with comprehensive error handling."""
    try:
        element = page.locator(selector)
        await element.wait_for(state="visible", timeout=5000)
        await element.click()
        return True, None
    
    except TimeoutError:
        return False, "Element not visible within timeout"
    
    except Error as e:
        if "Element is not attached" in str(e):
            return False, "Element was removed from DOM"
        if "Element is outside" in str(e):
            return False, "Element is outside viewport"
        if "intercept" in str(e).lower():
            return False, "Click was intercepted by another element"
        return False, str(e)
```

### 5.7 Network Interception

**Capture all network traffic:**

```python
async def setup_network_capture(page: Page, recorder: Recorder) -> None:
    """Attach handlers to capture network activity."""
    
    async def handle_request(request: Request) -> None:
        entry = NetworkEntry(
            timestamp=datetime.now(),
            request_url=request.url,
            request_method=request.method,
            request_headers=dict(request.headers),
            request_body=request.post_data,
            resource_type=request.resource_type,
            # Response fields filled in later
            response_status=None,
            response_headers=None,
            response_body=None,
            duration_ms=0,
        )
        recorder.pending_requests[request.url] = entry
    
    async def handle_response(response: Response) -> None:
        url = response.url
        if url in recorder.pending_requests:
            entry = recorder.pending_requests.pop(url)
            entry.response_status = response.status
            entry.response_headers = dict(response.headers)
            
            # Only capture body for interesting content types
            content_type = response.headers.get("content-type", "")
            if "json" in content_type or "xml" in content_type or "html" in content_type:
                try:
                    entry.response_body = await response.text()
                except:
                    pass
            
            recorder.network_log.append(entry)
    
    page.on("request", handle_request)
    page.on("response", handle_response)
```

---

## 6. Project Structure

```
bin_collection_scraper/
├── pyproject.toml
├── README.md
├── config/
│   ├── default.json              # Global configuration
│   └── overrides.json            # Per-council overrides
├── data/
│   └── councils.json             # Council list with URLs and postcodes
├── src/
│   └── bin_scraper/
│       ├── __init__.py
│       ├── main.py               # CLI entry point
│       ├── runner.py             # Runner class
│       ├── session.py            # Session class
│       ├── observer.py           # Observer class and Observation models
│       ├── strategist.py         # Strategist class and Rule classes
│       ├── executor.py           # Executor class
│       ├── recorder.py           # Recorder class
│       ├── config.py             # Configuration loading
│       ├── models.py             # Shared data classes
│       └── rules/
│           ├── __init__.py
│           ├── base.py           # Rule abstract base class
│           ├── cookie_consent.py # DismissCookieConsentRule
│           ├── fill_postcode.py
│           ├── click_submit.py
│           ├── select_address.py
│           └── ...
├── tests/
│   ├── conftest.py
│   ├── test_observer.py
│   ├── test_strategist.py
│   ├── test_executor.py
│   └── fixtures/
│       └── sample_pages/         # HTML fixtures for testing
└── output/                       # Generated output (gitignored)
    ├── preflight_report.json     # Results of pre-flight validation
    ├── birmingham/
    │   ├── network.jsonl         # Streamed network traffic (JSONL)
    │   ├── actions.jsonl         # Streamed action log (JSONL)
    │   ├── observations.jsonl    # Streamed observations (JSONL)
    │   └── screenshots/
    │       ├── 001_initial.png
    │       ├── 002_after_fill.png
    │       └── ...
    ├── manchester/
    └── ...
```

---

## 7. Dependencies

```toml
# pyproject.toml

[project]
name = "bin-collection-scraper"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "playwright>=1.40.0",
    "pydantic>=2.0.0",           # For data validation
    "rich>=13.0.0",              # For CLI output
    "aiofiles>=23.0.0",          # For async file operations
    "aiohttp>=3.9.0",            # For pre-flight HTTP checks
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-playwright>=0.4.0",
]
```

**Post-install:**
```bash
# Install Playwright browsers
playwright install chromium
```

---

## 8. Usage

### 8.1 CLI Interface

```bash
# Run pre-flight validation only (quick check before full run)
python -m bin_scraper preflight --councils data/councils.json --output output/

# Run all councils
python -m bin_scraper run --councils data/councils.json --output output/

# Run a single council (for testing)
python -m bin_scraper run-single --council birmingham --output output/

# Run with custom config
python -m bin_scraper run --config config/custom.json --councils data/councils.json

# Resume a partial run
python -m bin_scraper run --councils data/councils.json --output output/ --resume

# Skip pre-flight validation (if you've already run it)
python -m bin_scraper run --councils data/councils.json --output output/ --skip-preflight

# Generate report from existing output
python -m bin_scraper report --output output/
```

### 8.2 Programmatic Usage

```python
import asyncio
from bin_scraper import Runner, Config, load_councils

async def main():
    config = Config(headless=False)  # Show browser for debugging
    councils = load_councils("data/councils.json")
    
    runner = Runner(councils, "output/", config)
    results = await runner.run()
    
    print(f"Success: {results.success_count}")
    print(f"Failed: {results.failure_count}")

asyncio.run(main())
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

Test individual components with mock data:

- **Observer tests**: Given HTML fixtures, verify correct element detection
- **Strategist tests**: Given observations and history, verify correct action proposals
- **Executor tests**: Use Playwright's test fixtures to verify action execution

### 9.2 Integration Tests

Test the full flow against controlled HTML pages:

```python
# tests/test_integration.py

@pytest.fixture
def simple_postcode_page(page: Page):
    """A simple page with postcode form."""
    html = """
    <form>
        <label for="postcode">Postcode</label>
        <input type="text" id="postcode" name="postcode">
        <button type="submit">Find</button>
    </form>
    """
    page.set_content(html)
    return page

async def test_simple_postcode_flow(simple_postcode_page):
    session = Session(simple_postcode_page, ...)
    result = await session.run()
    
    assert result.status in ("success", "no_more_actions")
    assert any(a.action_type == "fill" for a, _ in result.history)
```

### 9.3 Live Tests (Manual)

For validating against real council sites:

```bash
# Test against a few known councils
python -m bin_scraper test-live --councils birmingham,manchester,leeds
```

---

## 10. Debugging and Troubleshooting

### 10.1 Headed Mode

Run with browser visible:
```python
config = Config(headless=False)
```

### 10.2 Slow Motion

Add delays to see what's happening:
```python
# In browser launch
browser = await playwright.chromium.launch(
    headless=False,
    slow_mo=500,  # 500ms delay between actions
)
```

### 10.3 Debug Logging

Use Python's logging module:
```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("bin_scraper")

# In Session
logger.debug(f"Observation: {observation.url}, {len(observation.inputs)} inputs")
logger.debug(f"Executing action: {action}")
```

### 10.4 Screenshots on Every Step

Enable in config:
```python
config = Config(screenshot_on_action=True)
```

### 10.5 Inspecting Recordings

The output files use JSONL (JSON Lines) format - one JSON object per line. Use `jq` for quick inspection:

```bash
# See all XHR requests
jq -c 'select(.resource_type == "xhr") | .request_url' output/birmingham/network.jsonl

# See action sequence
jq '.action.description' output/birmingham/actions.jsonl

# Filter to API-like requests (for analysis)
jq -c 'select(.resource_type == "xhr" or .resource_type == "fetch")' output/birmingham/network.jsonl > api_requests.jsonl

# Count requests by type
jq -s 'group_by(.resource_type) | map({type: .[0].resource_type, count: length})' output/birmingham/network.jsonl

# Find requests containing "postcode" in URL
jq -c 'select(.request_url | contains("postcode"))' output/birmingham/network.jsonl
```

---

## 11. Known Challenges and Mitigations

### 11.1 Cookie Consent Banners (GDPR)

Almost every UK council site displays a cookie consent banner. These can block interaction with the underlying form. Mitigation:
- **DismissCookieConsentRule** runs with highest priority (priority: 1)
- Detects banners via common patterns (class names, button text, nearby "cookie" text)
- Clicks accept/dismiss button before proceeding
- Re-checks on each iteration in case new banners appear after navigation

### 11.2 CAPTCHAs

Some councils use CAPTCHAs. Mitigation:
- Detect CAPTCHA presence (look for reCAPTCHA, hCaptcha elements)
- Flag the council for manual handling with `FailureCategory.CAPTCHA_PRESENT`
- Consider CAPTCHA-solving services if scale requires it (ethical considerations apply)

### 11.3 Rate Limiting

Some sites may rate limit requests. Mitigation:
- Add configurable delays between councils
- Implement exponential backoff on failures
- Respect robots.txt (optional, but good citizenship)

### 11.4 JavaScript-Heavy Sites

Some sites are SPAs that load everything dynamically. Mitigation:
- Wait for network idle before observing
- Look for loading indicators and wait for them to disappear
- Increase timeouts for slow sites

### 11.5 Inconsistent Markup

Council sites have wildly varying HTML quality. Mitigation:
- Multiple selector strategies (ID, name, label, proximity)
- Expanded keyword lists for fuzzy matching
- Relevance scoring rather than exact matching

### 11.6 Multi-Step Flows

Some sites have many steps before showing results. Mitigation:
- High iteration limit
- Clear progress tracking to avoid loops
- Per-council timeout overrides

---

## 12. Future Enhancements

These are out of scope for v1 but worth considering:

1. **Parallel execution**: Run multiple councils simultaneously
2. **Machine learning**: Train a model on successful flows to improve heuristics
3. **Visual diffing**: Detect when a council site has changed since last run
4. **API health monitoring**: Periodically verify discovered APIs still work
5. **Configuration UI**: Web interface for managing overrides and viewing results

---

## 13. Glossary

- **Council**: A UK local authority responsible for bin collection
- **Observation**: A structured snapshot of page state at a point in time
- **Action**: A single interaction with the page (fill, click, select)
- **Session**: A complete exploration attempt for one council
- **Settle**: The state when a page has finished loading and updating
- **Custom dropdown**: A non-native dropdown built with divs/JavaScript
- **UPRN**: Unique Property Reference Number, sometimes used for address lookup