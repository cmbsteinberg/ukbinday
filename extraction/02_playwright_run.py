import json
import time
from typing import List, Optional, Dict, Any
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from extraction.utils.error_handling import read_json, write_json
from extraction.utils.paths import paths

load_dotenv()


# ============================================================================
# NETWORK CAPTURE & PLAYWRIGHT EXECUTION
# ============================================================================


def should_capture_request(resource_type: str, url: str) -> bool:
    """Filter network requests to only capture relevant ones"""
    # Include these resource types
    if resource_type in ["xhr", "fetch", "document"]:
        # Exclude common noise
        noise_patterns = [
            "google-analytics",
            "googletagmanager",
            "doubleclick",
            "facebook.com/tr",
            "analytics",
            "pixel",
            "/ads/",
            "fonts.googleapis",
            "fonts.gstatic",
            ".woff",
            ".ttf",
            ".ico",
        ]

        url_lower = url.lower()
        return not any(pattern in url_lower for pattern in noise_patterns)

    return False


def execute_playwright_and_capture(
    council_name: str,
    playwright_code: str,
    input_params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute playwright code (synchronously) and capture network requests
    Returns dict with 'success' (bool) and 'requests' (list of captured network requests)
    Even on failure, returns any requests captured before the error occurred
    """
    captured_requests = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            # Set up network listener at context level (captures all pages)
            def handle_request(request):
                try:
                    resource_type = request.resource_type
                    url = request.url

                    if should_capture_request(resource_type, url):
                        request_data = {
                            "url": url,
                            "method": request.method,
                            "resourceType": resource_type,
                            "headers": request.headers,
                            "postData": request.post_data,
                        }

                        # Try to get response details when available
                        # Note: Skip response if browser/context is closing (CancelledError)
                        try:
                            response = request.response()
                            if response:
                                request_data["responseStatus"] = response.status
                                request_data["responseHeaders"] = response.headers
                        except Exception:
                            # This can fail if browser is closing or response not available
                            pass

                        captured_requests.append(request_data)
                except Exception as e:
                    print(f"  ⚠️  Error capturing request: {str(e)}")

            # Attach listener to context, not page
            context.on("request", handle_request)

            # Now create the page
            page = context.new_page()

            # Add parameter aliases/mappings for common variations
            params_with_aliases = dict(input_params)

            # If house_number exists but paon doesn't, map house_number to paon
            if (
                "house_number" in params_with_aliases
                and "paon" not in params_with_aliases
            ):
                params_with_aliases["paon"] = params_with_aliases["house_number"]

            # Extract common parameters from URL if not directly provided
            if "url" in params_with_aliases:
                from urllib.parse import urlparse, parse_qs

                url = params_with_aliases["url"]
                parsed = urlparse(url)
                query_params = parse_qs(parsed.query)

                # Extract UPRN from URL query params if not already in params
                if "uprn" not in params_with_aliases:
                    # Check various parameter names that might contain UPRN
                    for param_name in ["uprn", "brlu-selected-address", "UPRN"]:
                        if param_name in query_params and query_params[param_name]:
                            params_with_aliases["uprn"] = query_params[param_name][0]
                            break

            # Prepare execution context with input parameters
            # Include common variables that might be referenced
            exec_globals = {
                "page": page,
                "__builtins__": __builtins__,
                "kwargs": params_with_aliases,  # Some code expects kwargs dict
                **params_with_aliases,
            }

            # The playwright_code is async, so we need to strip await keywords
            sync_code = playwright_code.replace("await ", "")

            # Execute the code
            exec(sync_code, exec_globals, exec_globals)

            # Give some time for final requests to complete
            time.sleep(2)

            browser.close()

        return {"success": True, "requests": captured_requests}

    except Exception as e:
        print(f"  ❌ Error executing playwright: {str(e)}")
        import traceback

        traceback.print_exc()
        # Still return any requests captured before the error
        # This helps with debugging what happened before the failure
        return {"success": False, "requests": captured_requests}


# ============================================================================
# MAIN EXECUTION
# ============================================================================


def phase1_capture_network_logs():
    """Phase 1: Run all Playwright automation and capture network logs"""

    print("=" * 80, flush=True)
    print("PHASE 1: Capturing Network Logs from Playwright", flush=True)
    print("=" * 80, flush=True)

    # Load council extraction results
    print("Loading council_extraction_results.json...", flush=True)
    councils = read_json(paths.council_extraction_json, default=[])
    if not councils:
        print("❌ Failed to load council extraction results")
        return
    print(f"Loaded {len(councils)} councils", flush=True)

    # Load input.json for test parameters
    print("Loading input.json...", flush=True)
    input_params = read_json(paths.input_json, default={})
    print(f"Loaded {len(input_params)} council parameters", flush=True)

    # Filter for selenium councils with playwright_code
    print("Filtering for selenium councils...", flush=True)
    selenium_councils = [
        c
        for c in councils
        if c.get("data", {}).get("request_type") == "selenium"
        and c.get("data", {}).get("playwright_code")
    ]

    print(
        f"Found {len(selenium_councils)} councils using Selenium with playwright_code",
        flush=True,
    )

    # Track councils without playwright_code
    skipped = [
        c["council"]
        for c in councils
        if c.get("data", {}).get("request_type") == "selenium"
        and not c.get("data", {}).get("playwright_code")
    ]
    if skipped:
        print(f"\n⚠️  Skipping {len(skipped)} councils without playwright_code:")
        for council in skipped[:10]:
            print(f"  - {council}")
        if len(skipped) > 10:
            print(f"  ... and {len(skipped) - 10} more")

    results = []

    for i, council_data in enumerate(selenium_councils, 1):
        council_name = council_data["council"]
        playwright_code = council_data["data"]["playwright_code"]

        print(
            f"\n[{i}/{len(selenium_councils)}] Processing {council_name}...", flush=True
        )

        # Get input parameters for this council
        params = input_params.get(council_name, {})

        # Filter out metadata fields (keep 'url' as it's needed by playwright code)
        test_params = {
            k: v
            for k, v in params.items()
            if k
            not in [
                "LAD24CD",
                "wiki_name",
                "wiki_note",
                "wiki_command_url_override",
            ]
        }

        if not test_params:
            print("  ⚠️  No test parameters found in input.json, skipping")
            results.append(
                {
                    "council": council_name,
                    "status": "skipped",
                    "reason": "no_test_parameters",
                    "network_requests": [],
                }
            )
            continue

        print(f"  Using params: {list(test_params.keys())}")

        # Execute and capture
        result = execute_playwright_and_capture(
            council_name, playwright_code, test_params
        )

        network_requests = result["requests"]
        success = result["success"]

        if success:
            print(f"  ✅ Captured {len(network_requests)} network requests")
            results.append(
                {
                    "council": council_name,
                    "status": "success",
                    "playwright_code": playwright_code,
                    "test_params": test_params,
                    "network_requests": network_requests,
                }
            )
        else:
            # Failed but may have captured some requests before the error
            if network_requests:
                print(
                    f"  ⚠️  Failed but captured {len(network_requests)} requests before error"
                )
            else:
                print("  ❌ Failed with no network requests captured")

            results.append(
                {
                    "council": council_name,
                    "status": "failed",
                    "playwright_code": playwright_code,
                    "test_params": test_params,
                    "network_requests": network_requests,
                }
            )

    # Save network logs
    write_json(results, paths.playwright_network_logs_json)

    print(f"\n{'=' * 80}")
    print("PHASE 1 COMPLETE!")
    print(f"Processed: {len(selenium_councils)}")
    print(f"Success: {sum(1 for r in results if r['status'] == 'success')}")
    print(f"Failed: {sum(1 for r in results if r['status'] == 'failed')}")
    print(f"Skipped: {sum(1 for r in results if r['status'] == 'skipped')}")
    print("Saved to: playwright_network_logs.json")
    print(f"{'=' * 80}")


def main():
    """Run Phase 1: Capture network logs only"""
    print("Script starting...", flush=True)
    phase1_capture_network_logs()
    # Phase 2 will be run separately


if __name__ == "__main__":
    main()
