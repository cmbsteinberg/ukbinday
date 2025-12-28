import asyncio
import aiohttp
import json
from dotenv import load_dotenv
from extraction.utils.structured_output import CouncilExtraction
from extraction.utils.gemini import llm_call_with_struct_output
from extraction.utils.error_handling import write_json, print_summary, safe_execute
from extraction.utils.paths import paths

load_dotenv()


# ============================================================================
# PROCESSING FUNCTIONS
# ============================================================================


async def fetch_input_json(session: aiohttp.ClientSession) -> dict:
    """Fetch the test input.json to validate against"""
    async with session.get(paths.input_json_url) as resp:
        if resp.status != 200:
            print("⚠️  Failed to fetch input.json")
            return {}
        text = await resp.text()
        return safe_execute(
            lambda: json.loads(text),
            error_message="Failed to parse input.json",
            return_on_error={},
        )


async def process_council(
    session: aiohttp.ClientSession,
    council_file: dict,
    semaphore: asyncio.Semaphore,
    input_json: dict,
):
    file_name = council_file["name"]
    council_name = file_name.replace(".py", "")
    download_url = council_file["download_url"]

    async with semaphore:
        try:
            # Download source code
            async with session.get(download_url) as resp:
                if resp.status != 200:
                    return None
                code_content = await resp.text()

            # Get expected inputs from input.json for validation
            expected_inputs = input_json.get(council_name, {})
            expected_fields = [
                k
                for k in expected_inputs.keys()
                if k
                not in [
                    "LAD24CD",
                    "url",
                    "wiki_name",
                    "wiki_note",
                    "wiki_command_url_override",
                ]
            ]

            prompt = f"""Extract bin collection workflow for {council_name}.

Expected inputs: {expected_fields}

Classify request_type as:
- single_api (one API call)
- token_then_api (get token, then query)
- id_lookup_then_api (postcode→ID, then query)
- selenium (browser - convert to Playwright)
- calendar (date math only)

Extract: URLs, methods, selectors, date formats, Playwright code if needed.

CRITICAL - Multi-step URL Extraction:
⚠️ For multi-step processes, you MUST extract ALL URLs involved:
  - single_api: Provide 1 URL in api_urls list
  - token_then_api: Provide ALL URLs [token_url, api_url] - typically 2 URLs
    * If same endpoint used for both: provide 1 URL with 2 methods ["GET", "POST"]
  - id_lookup_then_api: Provide [lookup_url, data_url] - MUST have 2 URLs minimum
    * First URL: Where you lookup the ID/address from postcode
    * Second URL: Where you query bin data using the ID
  - api_urls must be a LIST containing all URLs in the order they're called
  - api_methods must be a LIST with one method per URL (e.g., ["POST", "GET"])

Example for id_lookup_then_api:
  api_urls: ["https://council.gov/address-lookup", "https://council.gov/bin-data"]
  api_methods: ["POST", "GET"]

If you identify a multi-step process, carefully read the code to find ALL endpoint URLs.
DO NOT provide only 1 URL if the process requires multiple steps.

IMPORTANT: If you provide playwright_code, it MUST be Python code using async/await syntax.
DO NOT use JavaScript syntax (const, let, var). Use Python syntax with await.

CODE:
{code_content}
"""
            extracted = llm_call_with_struct_output(
                prompt=prompt,
                response_schema=CouncilExtraction,
            )
            # Validate against input.json
            extracted_inputs = set(extracted.get("required_user_input", []))
            expected_inputs_set = set(expected_fields)

            if extracted_inputs != expected_inputs_set:
                print(
                    f"⚠️  {council_name}: Input mismatch - expected {expected_inputs_set}, got {extracted_inputs}"
                )
            else:
                print(f"✅ {council_name}")

            return {
                "council": council_name,
                "data": extracted,
                "validation": {
                    "expected_inputs": expected_fields,
                    "extracted_inputs": list(extracted_inputs),
                    "match": extracted_inputs == expected_inputs_set,
                },
            }

        except Exception as e:
            print(f"❌ {council_name}: {str(e)}")
            return None


async def main():
    semaphore = asyncio.Semaphore(50)

    async with aiohttp.ClientSession() as session:
        print("Fetching input.json for validation...")
        input_json = await fetch_input_json(session)
        print(f"Loaded {len(input_json)} council configs from input.json\n")

        print("Fetching council scripts from GitHub...")
        async with session.get(paths.github_api_url) as resp:
            if resp.status != 200:
                print("Failed to access GitHub")
                return
            files = await resp.json()

        python_files = [f for f in files if f["name"].endswith(".py")]
        print(f"Starting async extraction for {len(python_files)} scripts...\n")

        tasks = [
            process_council(session, f, semaphore, input_json) for f in python_files
        ]
        results = await asyncio.gather(*tasks)

        # Filter and save
        final_results = [r for r in results if r is not None]

        # Summary stats
        total = len(final_results)
        matched = sum(
            1 for r in final_results if r.get("validation", {}).get("match", False)
        )

        # Save results
        write_json(final_results, paths.council_extraction_json)

        # Print summary
        print(f"\n{'=' * 60}")
        print(f"🚀 Completed! Saved {total} extractions")
        if total > 0:
            print(
                f"✅ Validation matched: {matched}/{total} ({matched / total * 100:.1f}%)"
            )
        else:
            print("⚠️  No extractions succeeded")
        print("📄 Output: council_extraction_results.json")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
