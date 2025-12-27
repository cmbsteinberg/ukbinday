import json
import yaml
import re
from pathlib import Path
from typing import Dict, Any, Optional


# ============================================================================
# CONFIGURATION
# ============================================================================

COUNCIL_EXTRACTION_JSON = "extraction/data/council_extraction_results.json"
NETWORK_ANALYSIS_JSON = "extraction/data/network_analysis_results.json"
INPUT_JSON = "extraction/data/input.json"
OUTPUT_DIR = "extraction/data/councils"

# ============================================================================
# TEST INPUT EXTRACTION
# ============================================================================


def extract_test_inputs(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract test inputs from input.json entry

    Args:
        input_data: Single council entry from input.json

    Returns:
        Dictionary of test inputs (uprn, postcode, etc.)
    """
    test_inputs = {}

    # Direct fields
    if "uprn" in input_data:
        test_inputs["uprn"] = input_data["uprn"]
    if "postcode" in input_data:
        test_inputs["postcode"] = input_data["postcode"]

    # Extract UPRN from URL if present
    if "url" in input_data and "uprn" not in test_inputs:
        url = input_data["url"]
        # Match various UPRN patterns in URLs:
        # - ?uprn=12345
        # - brlu-selected-address=12345
        # - /uprn/12345
        # - uprn-12345
        uprn_patterns = [
            r'[?&]uprn[=:](\d+)',
            r'brlu-selected-address[=:](\d+)',
            r'/uprn[/-](\d+)',
            r'uprn[_-](\d+)',
            r'UPRN[=:](\d+)',
        ]
        for pattern in uprn_patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                test_inputs["uprn"] = match.group(1)
                break

    # Extract postcode from URL if present
    if "url" in input_data and "postcode" not in test_inputs:
        url = input_data["url"]
        # UK postcode pattern
        postcode_pattern = r'\b([A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2})\b'
        match = re.search(postcode_pattern, url, re.IGNORECASE)
        if match:
            test_inputs["postcode"] = match.group(1)

    # Extract other common parameters from URL
    if "url" in input_data:
        url = input_data["url"]

        # Extract house number (paon)
        paon_patterns = [
            r'[?&]paon[=:](\d+)',
            r'houseNumber[=:](\d+)',
        ]
        for pattern in paon_patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                test_inputs["paon"] = match.group(1)
                break

        # Extract USRN
        usrn_patterns = [
            r'[?&]usrn[=:](\d+)',
        ]
        for pattern in usrn_patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                test_inputs["usrn"] = match.group(1)
                break

    return test_inputs


# ============================================================================
# CONVERSION FUNCTIONS
# ============================================================================


def auto_correct_request_type(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Auto-correct misclassified request types

    Fix common LLM extraction mistakes:
    - id_lookup_then_api with only 1 URL should likely be single_api
    - id_lookup_then_api where description doesn't mention two steps
    """
    request_type = config.get("request_type")
    api_urls = config.get("api_urls", [])
    api_methods = config.get("api_methods", [])
    description = (config.get("api_description") or "").lower()

    # If id_lookup_then_api but only 1 URL and 1 method, likely misclassified
    if request_type == "id_lookup_then_api":
        if api_urls and api_methods and len(api_urls) == 1 and len(api_methods) == 1:
            # Check if description mentions two-step process
            two_step_indicators = [
                "then a post", "followed by", "final post", "second request",
                "initial get", "first get", "lookup", "search for address"
            ]

            has_two_step_description = any(indicator in description for indicator in two_step_indicators)

            if not has_two_step_description:
                # Likely should be single_api
                config["request_type"] = "single_api"
                config["api_description"] = (
                    "[AUTO-CORRECTED from id_lookup_then_api] " +
                    config.get("api_description", "")
                )

    return config


def merge_council_data(
    extraction_data: Optional[Dict[str, Any]],
    network_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Merge data from both extraction sources

    Priority:
    - Network analysis data is preferred for api_urls, api_methods (more accurate)
    - Extraction data provides response_format, bin_selector, date_format (parsing info)
    """

    # Start with base from network analysis if available, else extraction
    if network_data:
        analysis = network_data.get("analysis", {})
        base_config = {
            "council": network_data.get("council"),
            "request_type": analysis.get("alternative_request_type"),
            "required_user_input": analysis.get("required_user_input", []),
            "api_urls": analysis.get("api_urls"),
            "api_methods": analysis.get("api_methods"),
            "api_description": analysis.get("api_description"),
        }

        # Add optional network analysis fields
        if analysis.get("api_headers"):
            base_config["api_headers"] = analysis["api_headers"]
        if analysis.get("api_payload_example"):
            base_config["api_payload_example"] = analysis["api_payload_example"]
    else:
        # Use extraction data only
        data = extraction_data.get("data", {})
        base_config = {
            "council": extraction_data.get("council"),
            "request_type": data.get("request_type"),
            "required_user_input": data.get("required_user_input", []),
            "api_urls": data.get("api_urls"),
            "api_methods": data.get("api_methods"),
            "api_description": data.get("api_description"),
        }

    # Auto-correct misclassified request types
    base_config = auto_correct_request_type(base_config)

    # Add parsing info from extraction data if available
    if extraction_data:
        data = extraction_data.get("data", {})

        if data.get("response_format"):
            base_config["response_format"] = data["response_format"]
        if data.get("bin_selector"):
            base_config["bin_selector"] = data["bin_selector"]
        if data.get("date_format"):
            base_config["date_format"] = data["date_format"]

    return base_config


def convert_json_to_yaml():
    """Convert both JSON files to individual YAML files per council"""

    print("=" * 80)
    print("Converting JSON to YAML files")
    print("=" * 80)

    # Load all input JSON files
    print(f"\nLoading {COUNCIL_EXTRACTION_JSON}...")
    with open(COUNCIL_EXTRACTION_JSON, "r") as f:
        extraction_councils = json.load(f)
    print(f"Loaded {len(extraction_councils)} councils from initial extraction")

    print(f"\nLoading {NETWORK_ANALYSIS_JSON}...")
    with open(NETWORK_ANALYSIS_JSON, "r") as f:
        network_councils = json.load(f)
    print(f"Loaded {len(network_councils)} councils from network analysis")

    print(f"\nLoading {INPUT_JSON}...")
    with open(INPUT_JSON, "r") as f:
        input_test_data = json.load(f)
    print(f"Loaded {len(input_test_data)} councils from input.json (test data)")

    # Create lookup dictionaries by council name
    extraction_by_name = {c["council"]: c for c in extraction_councils}
    network_by_name = {c["council"]: c for c in network_councils}

    print(f"\nTotal councils: {len(extraction_by_name)}")
    print(f"Councils with network analysis (selenium refinement): {len(network_by_name)}")

    # Categorize councils
    # Process all extraction councils, using network analysis as override where available
    api_ready = []
    selenium_councils = []
    skipped = []

    for council_name, extraction_data in sorted(extraction_by_name.items()):
        network_data = network_by_name.get(council_name)

        # Determine final request type (network analysis overrides extraction if present)
        if network_data:
            # This council was selenium initially, but network analysis may have found a simpler way
            final_request_type = network_data.get("analysis", {}).get("alternative_request_type")
        else:
            # Use original extraction result
            final_request_type = extraction_data.get("data", {}).get("request_type")

        # Categorize based on final request type
        if final_request_type == "selenium":
            # Still requires selenium/playwright
            selenium_councils.append({
                "name": council_name,
                "extraction_data": extraction_data,
                "network_data": network_data,
                "source": "network_analysis" if network_data else "extraction",
            })
        elif final_request_type in ["single_api", "token_then_api", "id_lookup_then_api", "calendar"]:
            # Can be implemented with HTTP requests
            api_ready.append({
                "name": council_name,
                "extraction_data": extraction_data,
                "network_data": network_data,
            })
        else:
            # No valid request type (None or unclear)
            skipped.append(council_name)

    print(f"\nCategories:")
    print(f"  API-ready: {len(api_ready)}")
    print(f"  Selenium (holding patterns): {len(selenium_councils)}")
    print(f"  Skipped (no valid request type): {len(skipped)}\n")

    # Create output directory
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)

    # Convert API-ready councils to YAML
    api_count = 0
    print("Processing API-ready councils:")
    for council_info in api_ready:
        council_name = council_info["name"]
        config = merge_council_data(
            council_info["extraction_data"],
            council_info["network_data"],
        )

        # Add test inputs from input.json if available
        if council_name in input_test_data:
            test_inputs = extract_test_inputs(input_test_data[council_name])
            if test_inputs:
                config["test_inputs"] = test_inputs

        yaml_file = output_path / f"{council_name}.yaml"
        with open(yaml_file, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        print(f"✅ {council_name}.yaml")
        api_count += 1

    # Create holding patterns for Selenium councils
    selenium_from_network = []
    selenium_from_extraction = []

    print("\nCreating holding patterns for Selenium councils:")
    for council_info in selenium_councils:
        council_name = council_info["name"]
        extraction_data = council_info["extraction_data"]
        network_data = council_info["network_data"]

        # Track which source flagged it as selenium
        if council_info["source"] == "network_analysis":
            selenium_from_network.append(council_name)
        else:
            selenium_from_extraction.append(council_name)

        # Get required inputs from either source
        if network_data:
            analysis = network_data.get("analysis", {})
            required_inputs = analysis.get("required_user_input", [])
            description = analysis.get("api_description") or analysis.get("simplification_notes")
        else:
            data = extraction_data.get("data", {})
            required_inputs = data.get("required_user_input", [])
            description = data.get("api_description")

        # Create minimal config marking it as selenium
        config = {
            "council": council_name,
            "request_type": "selenium",
            "required_user_input": required_inputs,
            "status": "not_implemented",
            "notes": "Requires Playwright/Selenium automation - not yet implemented as HTTP requests",
            "api_description": description,
        }

        # Add test inputs from input.json if available
        if council_name in input_test_data:
            test_inputs = extract_test_inputs(input_test_data[council_name])
            if test_inputs:
                config["test_inputs"] = test_inputs

        yaml_file = output_path / f"{council_name}.yaml"
        with open(yaml_file, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        print(f"⏸️  {council_name}.yaml (selenium - {council_info['source']})")

    # Summary
    print(f"\n{'=' * 80}")
    print(f"Conversion complete!")
    print(f"{'=' * 80}")
    print(f"API-ready: {api_count} councils")
    print(f"Selenium (total): {len(selenium_councils)} councils")
    print(f"  - From network analysis: {len(selenium_from_network)} councils")
    print(f"  - From extraction only: {len(selenium_from_extraction)} councils")
    print(f"Skipped (no valid request type): {len(skipped)} councils")
    print(f"\nOutput directory: {output_path.absolute()}")
    print(f"{'=' * 80}")

    # Log selenium councils from network analysis
    if selenium_from_network:
        print(f"\n{'=' * 80}")
        print("Councils flagged as Selenium from network analysis:")
        print(f"{'=' * 80}")
        for council_name in sorted(selenium_from_network):
            print(f"  - {council_name}")
        print(f"{'=' * 80}")


if __name__ == "__main__":
    convert_json_to_yaml()
