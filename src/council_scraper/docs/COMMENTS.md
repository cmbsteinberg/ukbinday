Critical Issues

  1. Observer Selectors Are Broken (observer.py:123, observer.py:180, observer.py:224)

  The generated selectors are completely wrong:
  elem_selector = f"{selector}:nth-of-type({i})"

  This constructs selectors like input[type='text']:nth-of-type(0) which:
  - Uses :nth-of-type(0) - CSS nth-of-type is 1-indexed, not 0-indexed
  - Doesn't uniquely identify elements - nth-of-type counts siblings of the same tag, not matching selectors
  - Will fail silently when passed to the Executor

  The spec suggested using a combination of ID, name, and unique attributes to build reliable selectors. This
  implementation will likely click the wrong elements or fail to find them.

  2. Recorder Has a Race Condition (recorder.py:51-76)

  The response handler _on_response tries to match responses to requests by URL prefix:
  for key in list(self._pending_requests.keys()):
      if key.startswith(url + ":"):
          matching_key = key
          break

  This breaks when:
  - Multiple concurrent requests to the same URL (will match wrong request)
  - Redirects (response URL differs from request URL)
  - The first match wins, orphaning later requests

  The spec suggested using request object identity or a proper correlation mechanism.

  3. Observer State Leaks Across Sessions (observer.py:22)

  self._previous_element_selectors: set[str] = set()

  The Observer maintains state in _previous_element_selectors, but Session creates a single Observer instance
  and reuses it. If you ran multiple sessions (which the Runner does), this state would leak. Currently the
  Session creates a new Observer each time, but this is fragile - the Observer was designed to be stateless per
   the spec.

  ---
  Serious Issues

  4. Missing Type in Imports (executor.py:5)

  from playwright.async_api import Error, Page, TimeoutError

  TimeoutError shadowing - this shadows Python's built-in TimeoutError. The code happens to work because
  Playwright's is the one being caught, but this is asking for trouble. Should use
  playwright.async_api.TimeoutError as PlaywrightTimeoutError.

  5. Error Detection Too Aggressive (observer.py:58-60, session.py:170-194)

  self.error_keywords = [
      ...
      "not found",
      "error",
  ]

  These keywords will match legitimate content like "Find out more" or "error-free service". The spec was more
  careful about using full phrases. Combined with _is_dead_end() returning True on any match, this will
  prematurely abort on valid pages.

  6. Missing import re in Session (session.py:163)

  import re
  if re.search(r"\d{1,2}\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", text_lower):

  This import is inside a method, which works but is terrible practice. It should be at module level.

  7. Recorder Response Handler Isn't Async-Safe (recorder.py:31)

  page.on("response", lambda response: self._on_response(response))

  This wraps an async method but doesn't await it. Playwright will call this synchronously, and the async
  _on_response will return a coroutine object that's never awaited. Response bodies won't be captured.

  ---
  Design Issues

  8. Strategist Filtering Logic Is Confused (strategist.py:363-372)

  has_tried = any(
      (entry.action.action_type, entry.action.selector, entry.action.value) == key
      for entry in history[-5:]
      if entry.action.action_type in ("fill", "select")
  )

  if not has_tried or action.action_type == "click":

  This logic is convoluted. Click actions always pass the filter regardless of has_tried, which defeats the
  purpose of deduplication. The spec intended for clicks to be retried only if page state changed
  significantly.

  9. No Exponential Backoff or Rate Limiting (runner.py)

  The spec mentioned rate limiting mitigations, but there's zero delay between councils. Hammering 350 council
  websites sequentially will likely get you blocked.

  10. CustomDropdown Selector Generation Is Useless (strategist.py:237)

  selector=f"{dropdown.trigger_selector}:first-of-type",

  This appends :first-of-type to whatever the trigger selector is, which makes no sense. If trigger_selector is
   [role='combobox']:nth-of-type(0), this becomes [role='combobox']:nth-of-type(0):first-of-type - invalid CSS.

  ---
  Code Quality Issues

  11. Bare except Clauses Everywhere

  Multiple instances of except Exception: or except: that swallow errors silently:
  - observer.py:161-162
  - observer.py:206-208
  - observer.py:307-308
  - recorder.py:72

  This makes debugging impossible. At minimum, log the exception.

  12. Spec Divergence: TestData vs test_postcode

  The spec defined a TestData class, but the implementation just passes test_postcode: str directly. This makes
   extending to support test_address (which the spec allows) awkward.

  13. No Async Context Manager for Recorder (recorder.py:115-119)

  def __enter__(self):
      return self

  def __exit__(self, exc_type, exc_val, exc_tb):
      self.close()

  These are sync context managers, but the code is async. Should implement __aenter__ and __aexit__. Currently
  Runner.run_single manually calls recorder.close() which works, but the context manager pattern is broken.

  14. Report Uses Dunder Import (runner.py:214)

  "timestamp": __import__('datetime').datetime.now().isoformat(),

  Why? datetime is already imported at the top of the file for type hints. This is either cargo-culted or
  deliberately obfuscated.

  ---
  Minor Issues

  - Unused re import at module level in observer.py (only used in runner.py)
  - No logging - the spec mentioned debug logging but there's none
  - time imported but could use datetime in executor.py
  - Inconsistent naming: elem_selector vs selector, btn vs button
  - Magic numbers: [:1000], [:50], [-5:], > 0.3 - should be config

  ---
  What Actually Works

  - The overall architecture matches the spec reasonably well
  - The rule priority system is correctly implemented
  - Basic happy-path flow (fill postcode -> click submit -> detect success) probably works
  - JSONL streaming to disk is implemented correctly
  - Cookie consent detection logic is decent

  ---
  Verdict

  This feels like someone used an LLM to generate code from the spec without deeply understanding Playwright or
   async Python. The architecture is there, but the implementation details are riddled with bugs. Running this
  against 350 councils will produce unreliable results, and the broken selectors mean any failures will be
  difficult to debug.

  I'd estimate 40-60% of councils would fail due to implementation bugs rather than actual site difficulties.