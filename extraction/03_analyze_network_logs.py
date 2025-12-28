import asyncio
import json
from typing import List, Dict, Any
from dotenv import load_dotenv
from extraction.utils.structured_output import NetworkAnalysisResult
from extraction.utils.gemini import llm_call_with_struct_output
from extraction.utils.error_handling import read_json, write_json
from extraction.utils.paths import paths

load_dotenv()


# ============================================================================
# PROCESSING FUNCTIONS
# ============================================================================


async def analyze_council_network(
    council_data: Dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> Dict[str, Any]:
    """
    Analyze network logs for a single council to determine if playwright
    can be replaced with simple requests
    """
    council_name = council_data["council"]
    network_requests = council_data.get("network_requests", [])
    playwright_code = council_data.get("playwright_code", "")
    test_params = council_data.get("test_params", {})

    async with semaphore:
        try:
            # Format network requests for LLM analysis (if any)
            formatted_requests = []
            for req in network_requests:
                formatted_req = {
                    "url": req.get("url"),
                    "method": req.get("method"),
                    "resourceType": req.get("resourceType"),
                    "status": req.get("responseStatus"),
                }
                # Include headers if they look important
                if req.get("headers"):
                    # Filter out common browser headers
                    important_headers = {
                        k: v
                        for k, v in req.get("headers", {}).items()
                        if k.lower()
                        in [
                            "content-type",
                            "authorization",
                            "x-api-key",
                            "x-csrf-token",
                            "cookie",
                        ]
                    }
                    if important_headers:
                        formatted_req["headers"] = important_headers

                # Include POST data if present
                if req.get("postData"):
                    formatted_req["postData"] = req.get("postData")

                formatted_requests.append(formatted_req)

            # Build prompt
            network_section = ""
            if formatted_requests:
                network_section = f"""
CAPTURED NETWORK REQUESTS ({len(formatted_requests)} total):
{json.dumps(formatted_requests, indent=2)}
"""
            else:
                network_section = """
CAPTURED NETWORK REQUESTS: None (playwright execution may have failed before capturing requests)
NOTE: Analyze the playwright code to infer what requests would be made.
"""

            prompt = f"""Analyze the Playwright automation for {council_name}.

TASK: Determine if this Playwright automation can be simplified to direct HTTP requests (using Python requests library).

PLAYWRIGHT CODE:
```python
{playwright_code}
```

TEST PARAMETERS USED:
{json.dumps(test_params, indent=2)}
{network_section}

ANALYSIS REQUIREMENTS:
1. Identify which network requests are actually needed to get bin collection data
2. Determine if Playwright is truly necessary or if simple requests would work
3. Specify the alternative_request_type (or null if unclear):
   - single_api: One API call returns data
   - token_then_api: First get token/session, then query
   - id_lookup_then_api: First lookup ID from postcode, then query with ID
   - selenium: Browser automation is still required (e.g., heavy JavaScript, CAPTCHAs, complex interactions)
   - calendar: Just date calculation, no requests needed
   - null: Cannot determine a clear alternative (explain why in simplification_notes)

4. Extract (when applicable):
   - The key API URLs needed
   - HTTP methods (GET/POST)
   - Required headers (auth tokens, content-type, etc.)
   - Example payload for POST requests
   - Required user inputs (postcode, uprn, etc.)

5. Rate your confidence: high (very clear), medium (likely works), low (uncertain)

CRITICAL - Multi-step URL Extraction:
⚠️ If you classify as token_then_api or id_lookup_then_api, you MUST provide ALL URLs in sequence:
  - token_then_api: Provide [token_url, api_url] - typically 2 URLs (or 1 URL if same endpoint)
  - id_lookup_then_api: Provide [lookup_url, data_url] - MUST have 2 URLs minimum
  - api_urls must be a LIST with all URLs in order
  - api_methods must be a LIST matching each URL (e.g., ["GET", "POST"])

If you describe a multi-step process but only provide 1 URL, the config will be INVALID and fail validation.

Focus on the ESSENTIAL requests that return bin data, ignore analytics/tracking/static resources.
"""

            # Call LLM
            analysis = await llm_call_with_struct_output(
                prompt=prompt,
                response_schema=NetworkAnalysisResult,
            )

            print(
                f"✅ {council_name}: {analysis['alternative_request_type']} (confidence: {analysis['confidence']})"
            )

            return {
                "council": council_name,
                "original_status": council_data.get("status"),
                "analysis": analysis,
                "network_request_count": len(network_requests),
            }

        except Exception as e:
            print(f"❌ {council_name}: {str(e)}")
            import traceback

            traceback.print_exc()
            return None


async def main():
    """Phase 2: Analyze captured network logs to propose requests-based alternatives"""

    print("=" * 80)
    print("PHASE 2: Analyzing Network Logs for Simplification")
    print("=" * 80)

    # Load network logs from Phase 1
    print(f"\nLoading network logs from {paths.playwright_network_logs_json}...")
    network_logs = read_json(paths.playwright_network_logs_json, default=[])

    if not network_logs:
        print("❌ Failed to load network logs or file is empty")
        return

    print(f"Loaded {len(network_logs)} council network captures")

    # Analyze all councils (including failures that may have captured partial requests)
    councils_to_analyze = [
        c for c in network_logs if c.get("status") in ["success", "failed"]
    ]

    # Show breakdown
    with_requests = sum(
        1
        for c in councils_to_analyze
        if c.get("network_requests") and len(c["network_requests"]) > 0
    )
    without_requests = len(councils_to_analyze) - with_requests

    print(f"Found {len(councils_to_analyze)} councils to analyze:")
    print(f"  - {with_requests} with network requests captured")
    print(
        f"  - {without_requests} without network requests (will analyze playwright code only)\n"
    )

    # Limit concurrency to avoid rate limits
    semaphore = asyncio.Semaphore(10)

    # Process all councils asynchronously
    print("Starting async analysis...\n")
    tasks = [
        analyze_council_network(council, semaphore) for council in councils_to_analyze
    ]
    results = await asyncio.gather(*tasks)

    # Filter out None results
    final_results = [r for r in results if r is not None]

    # Save results
    write_json(final_results, paths.network_analysis_json)

    # Summary statistics
    total = len(final_results)
    if total > 0:
        by_type = {}
        by_confidence = {"high": 0, "medium": 0, "low": 0}

        for result in final_results:
            alt_type = result["analysis"]["alternative_request_type"]
            # Handle None values
            type_key = alt_type if alt_type is not None else "unclear"
            by_type[type_key] = by_type.get(type_key, 0) + 1

            confidence = result["analysis"]["confidence"]
            by_confidence[confidence] = by_confidence.get(confidence, 0) + 1

        print(f"\n{'=' * 80}")
        print(f"🚀 PHASE 2 COMPLETE!")
        print(f"{'=' * 80}")
        print(f"\nAnalyzed: {total} councils")
        print(f"\nBy Alternative Type:")
        for alt_type, count in sorted(by_type.items()):
            print(f"  {alt_type}: {count} ({count / total * 100:.1f}%)")
        print(f"\nBy Confidence:")
        for conf, count in sorted(by_confidence.items()):
            print(f"  {conf}: {count} ({count / total * 100:.1f}%)")
        print(f"\n📄 Output saved to: {paths.network_analysis_json}")
        print(f"{'=' * 80}")
    else:
        print("\n⚠️  No successful analyses")


if __name__ == "__main__":
    asyncio.run(main())
