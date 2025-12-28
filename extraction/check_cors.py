import httpx
import yaml
from pathlib import Path
import re
import asyncio


COUNCILS_DIR = Path("extraction/data/councils")
MAX_CONCURRENT_REQUESTS = 50


def load_council_config(council_name: str) -> dict:
    """Load YAML config for a specific council"""
    yaml_file = COUNCILS_DIR / f"{council_name}.yaml"

    if not yaml_file.exists():
        raise FileNotFoundError(f"No config found for council: {council_name}")

    with open(yaml_file, "r") as f:
        return yaml.safe_load(f)


def list_available_councils() -> list[str]:
    """List all councils with YAML configs"""
    if not COUNCILS_DIR.exists():
        return []

    return sorted([f.stem for f in COUNCILS_DIR.glob("*.yaml")])


def fill_url_template(url_template: str, test_inputs: dict) -> str:
    """Replace {placeholders} in URL with test values from config"""
    filled_url = url_template

    # Find all placeholders
    placeholders = re.findall(r"\{(\w+)\}", url_template)

    # Fallback sample data for placeholders not in test_inputs
    sample_data = {
        "postcode": "SW1A1AA",
        "uprn": "100023336956",
        "usrn": "12345678",
        "street": "High Street",
        "town": "London",
        "houseNumber": "10",
        "houseName": "Test House",
        "address": "10 Downing Street",
        "id": "12345",
        "propertyId": "12345",
        "sessionId": "test-session-id",
        "token": "test-token",
        "address_id": "12345",
    }

    for placeholder in placeholders:
        # Use test_inputs first, then fallback to sample data
        value = test_inputs.get(placeholder, sample_data.get(placeholder, f"sample_{placeholder}"))
        filled_url = filled_url.replace(f"{{{placeholder}}}", str(value))

    return filled_url


async def check_council_cors(
    council_name: str,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore
) -> list[str]:
    """Check CORS for a single council's URLs"""
    results = []

    try:
        config = load_council_config(council_name)
        request_type = config.get("request_type", "unknown")
        is_selenium = request_type == "selenium"

        # Get all URLs from config
        api_urls = config.get("api_urls", [])
        test_inputs = config.get("test_inputs", {})

        if not api_urls:
            results.append(f"{council_name:<30} | {request_type:<10} | {'N/A':<8} | {'N/A':<8} | No URLs in config")
            return results

        # Check each URL
        for url_template in api_urls:
            async with semaphore:
                try:
                    # Fill URL with test data from config
                    url = fill_url_template(url_template, test_inputs)

                    # Make request to check CORS
                    response = await client.head(
                        url, timeout=5, follow_redirects=True
                    )

                    # Check for CORS header
                    cors_header = response.headers.get("Access-Control-Allow-Origin")
                    has_cors = "Yes" if cors_header else "No"
                    success = "Yes" if 200 <= response.status_code < 300 else "No"

                    type_label = "selenium" if is_selenium else "http"
                    url_display = url[:60] + "..." if len(url) > 60 else url

                    results.append(f"{council_name:<30} | {type_label:<10} | {success:<8} | {has_cors:<8} | {url_display}")

                except (httpx.RequestError, httpx.TimeoutException):
                    type_label = "selenium" if is_selenium else "http"
                    url_display = url_template[:60] + "..." if len(url_template) > 60 else url_template
                    results.append(f"{council_name:<30} | {type_label:<10} | {'Error':<8} | {'N/A':<8} | {url_display}")

    except Exception as e:
        results.append(f"{council_name:<30} | {'error':<10} | {'Error':<8} | {'N/A':<8} | Config load failed: {str(e)[:30]}")

    return results


async def check_cors_for_councils():
    """Check CORS status for all council URLs asynchronously"""
    headers = {
        "Origin": "https://example.com",  # Simulate request from different origin
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    print(f"{'Council':<30} | {'Type':<10} | {'Success':<8} | {'CORS':<8} | {'URL'}")
    print("-" * 120)

    councils = list_available_councils()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async with httpx.AsyncClient(headers=headers, verify=False) as client:
        tasks = [
            check_council_cors(council_name, client, semaphore)
            for council_name in councils
        ]

        # Gather all results
        all_results = await asyncio.gather(*tasks)

        # Count statistics
        stats = {
            "cors_yes": 0,
            "cors_no": 0,
            "error": 0,
            "na": 0,
            "selenium": 0,
            "total_urls": 0
        }

        # Print results in order and collect stats
        for results in all_results:
            for result in results:
                print(result)
                stats["total_urls"] += 1

                # Parse by splitting on | and checking the CORS column (index 3)
                parts = [p.strip() for p in result.split("|")]
                if len(parts) >= 5:
                    cors_value = parts[3]
                    success_value = parts[2]

                    if cors_value == "Yes":
                        stats["cors_yes"] += 1
                    elif cors_value == "No":
                        stats["cors_no"] += 1
                    elif success_value == "Error":
                        stats["error"] += 1
                    elif cors_value == "N/A":
                        stats["na"] += 1

                    if parts[1] == "selenium":
                        stats["selenium"] += 1

        # Print summary
        print("\n" + "=" * 120)
        print("SUMMARY")
        print("=" * 120)
        print(f"Total URLs checked: {stats['total_urls']}")
        print(f"Total councils: {len(councils)}")
        print()

        # Calculate percentages for URLs that were actually checked (excluding N/A)
        checkable_urls = stats['total_urls'] - stats['na']

        if checkable_urls > 0:
            cors_yes_pct = (stats['cors_yes'] / checkable_urls) * 100
            cors_no_pct = (stats['cors_no'] / checkable_urls) * 100
            error_pct = (stats['error'] / checkable_urls) * 100

            print(f"CORS Enabled:  {stats['cors_yes']:4d} URLs ({cors_yes_pct:5.1f}%)")
            print(f"CORS Disabled: {stats['cors_no']:4d} URLs ({cors_no_pct:5.1f}%)")
            print(f"Errors:        {stats['error']:4d} URLs ({error_pct:5.1f}%)")
            print(f"N/A:           {stats['na']:4d} URLs (selenium/no config)")
            print()
            print(f"Selenium-based councils: {stats['selenium']} URLs")

        print("=" * 120)


if __name__ == "__main__":
    asyncio.run(check_cors_for_councils())
