Detailed Code Critique: UK Council Bin Collection Scraper

  Executive Summary

  The implementation follows the spec reasonably well at an architectural level. However, there are several
  remaining issues after the fixes were applied, along with new concerns. The COMMENTS.md and FIXES_APPLIED.md
  addressed the most egregious bugs, but the codebase still has significant room for improvement.

  ---
  Critical Issues (Still Present)

  1. CustomDropdown Selector Still Broken (observer.py:353)

  elem_selector = f"{selector}:nth-of-type({i})"

  The fix document claims selectors were fixed, but _find_custom_dropdowns() still uses 0-indexed 
  :nth-of-type(), which is invalid CSS (nth-of-type is 1-indexed). This was fixed for inputs and buttons but
  not for custom dropdowns.

  Impact: Custom dropdown detection will silently fail or target wrong elements.

  2. Input Selector Name Collision (observer.py:152-154)

  if input_type:
      elem_selector = f"{selector}[name='{name}']"
  else:
      elem_selector = f"[name='{name}']"

  If there are multiple inputs with the same name attribute (common in forms with arrays like address[]), this
  selector will match all of them, and Playwright's behavior becomes unpredictable.

  Better approach: Use [name='{name}']:nth({i}) or incorporate additional attributes like type, placeholder, or
   parent context.

  3. Memory Leak in Recorder (recorder.py:67-69)

  self._pending_requests[request_uuid] = entry
  self._request_id_map[id(request)] = request_uuid

  If a request never receives a response (connection reset, server timeout, cancelled navigation), entries
  remain in _pending_requests and _request_id_map forever. Over a 350-council run, this could accumulate
  significant memory.

  Fix needed: Periodic cleanup of stale pending requests (e.g., older than 60 seconds) or cleanup on page
  navigation.

  4. Race Condition in Observer's _get_label_for_element (observer.py:389-391)

  label = page.locator(f"label[for='{elem_id}']").first
  if await label.is_visible():
      return await label.text_content()

  This doesn't check if the label exists before calling is_visible(). If no label exists, label.first will
  still return a locator object, but is_visible() may throw or return false incorrectly. The outer try/except
  catches it, but it's sloppy.

  ---
  Serious Issues

  5. No Rate Limiting Between Councils (runner.py:68-71)

  for i, council in enumerate(councils_to_process):
      result = await self.run_single(browser, council)

  The spec explicitly mentioned rate limiting concerns, but there's no delay between councils. Running against
  350 council websites in rapid succession will likely trigger rate limiting, CAPTCHAs, or IP blocks on some
  councils that share infrastructure.

  Recommendation: Add configurable inter_council_delay_ms to Config.

  6. _get_nearby_text is Duplicated Logic (observer.py:406-410)

  text = await element.evaluate(
      """el => {
      let text = el.parentElement?.textContent || '';
      let siblings = el.parentElement?.textContent || '';  // BUG: Same as text!
      return (text + ' ' + siblings).substring(0, 200);
  }"""
  )

  This JavaScript concatenates parentElement.textContent with itself. The variable siblings should have
  different logic (e.g., actual sibling elements), but it just duplicates text.

  Impact: The nearby_text field provides less useful context than intended.

  7. Session Dead-End Detection Is Too Aggressive (session.py:236-237)

  if any(indicator in text_lower for indicator in dead_end_indicators):
      return True

  The indicators include "sign in" which will trigger false positives on legitimate pages that have a "Sign in"
   link in the header/footer (most council websites do). The FIXES_APPLIED.md improved the error keywords in
  Observer, but the Session's _is_dead_end() still uses overly broad terms.

  8. Loop Detection Counts Wrong Thing (session.py:252-258)

  url_count = sum(
      1
      for entry in self.history[-10:]
      if entry.observation.url == observation.url
  )
  if url_count > self.config.max_same_url_visits:
      return True

  This counts how many times the same URL appears in the history, not including the current observation. But if
   max_same_url_visits is 3, and we've visited 3 times before, this triggers on the 4th visit. The variable
  name is misleading - it's actually max_same_url_visits_before_abort.

  9. Spec Divergence: TestData vs Raw Postcode (strategist.py:19-21)

  def propose(
      self,
      observation: Observation,
      history: list[HistoryEntry],
      test_postcode: str,  # Spec had TestData class
  ) -> list[Action]:

  The spec defined a TestData class containing both test_postcode and test_address. The implementation passes
  just test_postcode as a string, making it awkward to extend for councils that require a full address input.
  This is a deliberate simplification but limits functionality.

  ---
  Design Issues

  10. Strategist Rules Can't Access Config (strategist.py:39-80)

  Individual rules have no access to the Config object. The Strategist has it, but rules are standalone. This
  means:
  - Rules can't adjust behavior based on config
  - No way to tune per-rule confidence scores from config
  - No way to disable specific rules via config

  11. No Retry Logic for Failed Actions (session.py:150-152)

  if not result.success:
      # Action failed, continue to next iteration to reassess
      continue

  When an action fails, the session just continues. The spec mentioned max_action_retries: int = 2 in Config,
  but this isn't implemented. Failed actions should potentially be retried with force-click or alternative
  selectors.

  12. Observation Hash Is Too Coarse (models.py:131-137)

  key_data = {
      "url": self.url,
      "text_sample": self.visible_text_sample[:100],  # Only 100 chars!
      "num_inputs": len(self.inputs),
      "num_buttons": len(self.buttons),
  }

  The hash only uses the first 100 characters of visible text. Two very different pages with the same header
  might hash the same. This makes loop detection unreliable.

  13. No Screenshot on Success/Failure by Default (session.py)

  The Config has screenshot_on_success: bool = True and screenshot_on_failure: bool = True, but Session never
  calls recorder.take_screenshot(). The screenshot capability exists but isn't used.

  14. Blocking File I/O in Async Context (recorder.py:107-108)

  self._network_file.write(json.dumps(asdict(entry), default=str) + "\n")
  self._network_file.flush()

  write() and flush() are synchronous file I/O called within async methods. With high network traffic, this
  blocks the event loop. The spec mentioned aiofiles as a dependency, but it's not used.

  ---
  Code Quality Issues

  15. Tests Are Integration Scripts, Not Unit Tests

  All test files (test_scraper.py, test_preflight.py, etc.) are integration scripts that:
  - Hit real websites
  - Require network access
  - Have no assertions (assert statements)
  - Can't run in CI

  There are zero unit tests for core logic:
  - No tests for relevance scoring algorithms
  - No tests for selector generation
  - No tests for rule proposal logic
  - No tests for failure classification

  16. Magic Numbers Throughout

  high_relevance_inputs = sorted(
      [inp for inp in observation.inputs if inp.relevance_score > 0.3 ...]  # Magic: 0.3
  )

  for btn in untried[:3]:  # Magic: 3

  if len(observation.visible_text_sample.strip()) < 100:  # Magic: 100

  These should be named constants or config options.

  17. Inconsistent Error Handling Patterns

  Some methods use try/except/continue:
  except Exception as e:
      console.log(f"[red]Error: {e}[/red]")
      continue

  Others return ExecutionResult with error info:
  return ExecutionResult(
      success=False,
      error_type="playwright_error",
      error_message=str(e),
  )

  The mix of patterns makes error flow harder to follow.

  18. Missing __all__ in Most Modules

  Only __init__.py has __all__. Other modules expose everything, including internal helpers, making the public
  API unclear.

  19. Unused Import (main.py:5)

  from pathlib import Path  # Never used

  ---
  Testing Gaps

  20. No HTML Fixtures for Unit Testing

  The spec mentioned:
  tests/
  └── fixtures/
      └── sample_pages/         # HTML fixtures for testing

  This directory doesn't exist. Without fixtures, you can't:
  - Test Observer against known page structures
  - Test Strategist rules deterministically
  - Run fast, offline tests

  21. Test Scripts Modify Global State

  test_list_path = "data/test_councils.json"
  with open(test_list_path, "w") as f:
      json.dump(test_councils, f, indent=2)

  Tests write to the main data/ directory rather than using temp files, risking data pollution.

  ---
  Security Considerations

  22. User-Agent Hardcoded (runner.py:107)

  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",

  This is a truncated, incomplete user-agent string and doesn't rotate. Some councils may block partial or
  static user-agents.

  23. No Robots.txt Checking

  The spec mentioned "Respect robots.txt (optional, but good citizenship)" but there's no implementation.
  Running against 350 councils without checking robots.txt could be considered aggressive scraping.

  ---
  What Works Well

  1. Architecture matches spec - Components are properly separated
  2. Streaming JSONL output - Survives crashes, easy to analyze
  3. Rule priority system - Clean, extensible design
  4. Failure categorization - 15 categories give good diagnostics
  5. Rich console output - Good visibility during runs
  6. Preflight validation - Catches bad data early
  7. Cookie consent handling - Priority 1 rule is smart
  8. Request/response UUID matching - Fixed the race condition properly
  9. Proper async patterns - Uses asyncio.create_task() correctly for response handler

  ---
  Recommendations

  High Priority

  1. Fix custom dropdown selector (0-indexed bug)
  2. Add rate limiting between councils
  3. Add memory cleanup for pending requests
  4. Create unit tests with HTML fixtures
  5. Extract magic numbers to constants/config

  Medium Priority

  6. Implement screenshot capture on success/failure
  7. Fix _get_nearby_text duplicated logic
  8. Narrow dead-end detection phrases
  9. Add TestData class per spec
  10. Use aiofiles for non-blocking I/O

  Low Priority

  11. Add robots.txt checking
  12. Rotate user-agents
  13. Add __all__ exports
  14. Clean up unused imports
  15. Add action retry logic

  ---
  Verdict

  The codebase has improved significantly from the initial review. The critical async bugs and race conditions
  were fixed. However, there's still a remaining critical bug (custom dropdown selector), no unit tests, and
  several design issues that will cause problems at scale.

  Estimated success rate against 350 councils: 50-70% (improved from the original 40-60% estimate, but still
  limited by selector issues and aggressive dead-end detection).