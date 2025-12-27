import yaml
import httpx
import json as json_lib
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Union
import re
import logging

# Optional: requests library for TLS fallback
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ============================================================================
# CONFIGURATION
# ============================================================================

COUNCILS_DIR = Path("extraction/data/councils")
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DEFAULT_TIMEOUT = 30
VERIFY_SSL = True  # Set to False to disable SSL verification for councils with cert issues
USE_REQUESTS_FALLBACK = True  # Try requests library if httpx fails with SSL errors

# Setup logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)


# ============================================================================
# COUNCIL CONFIG LOADING
# ============================================================================


def load_council_config(council_name: str) -> Dict[str, Any]:
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


# ============================================================================
# HEADER & PAYLOAD HELPERS
# ============================================================================


def extract_headers_from_description(description: str) -> Dict[str, str]:
    """Extract API keys and headers mentioned in the description"""
    headers = {}

    # Extract Ocp-Apim-Subscription-Key
    ocp_match = re.search(r"Ocp-Apim-Subscription-Key.*?['\"]([a-f0-9]+)['\"]", description, re.IGNORECASE)
    if ocp_match:
        headers["Ocp-Apim-Subscription-Key"] = ocp_match.group(1)

    # Extract generic API keys
    api_key_match = re.search(r"(?:api[_-]?key|apikey).*?['\"]([a-zA-Z0-9-]+)['\"]", description, re.IGNORECASE)
    if api_key_match and "Ocp-Apim-Subscription-Key" not in headers:
        headers["api-key"] = api_key_match.group(1)

    return headers


def prepare_headers(config: Dict[str, Any]) -> Dict[str, str]:
    """Prepare headers from config and description"""
    headers = dict(config.get("api_headers", {}))

    # Extract additional headers from description
    if config.get("api_description"):
        extracted = extract_headers_from_description(config["api_description"])
        headers.update(extracted)

    # Add default User-Agent if not present
    if "User-Agent" not in headers and "user-agent" not in headers:
        headers["User-Agent"] = DEFAULT_USER_AGENT

    return headers


def fill_url_template(url_template: str, inputs: Dict[str, Any]) -> str:
    """Replace {placeholders} in URL with actual values"""
    filled_url = url_template

    for key, value in inputs.items():
        filled_url = filled_url.replace(f"{{{key}}}", str(value))

    # Check if there are still unfilled placeholders
    remaining = re.findall(r"\{(\w+)\}", filled_url)
    if remaining:
        raise ValueError(f"Missing required inputs: {remaining}")

    return filled_url


def prepare_payload(
    config: Dict[str, Any],
    inputs: Dict[str, Any],
    response_format: Optional[str] = None
) -> Tuple[Any, Optional[str]]:
    """
    Prepare payload for POST request

    Returns:
        Tuple of (payload, content_type)
    """
    payload_example = config.get("api_payload_example")

    if not payload_example:
        # Try to infer from response_format and inputs
        if response_format == "json" or "json" in config.get("api_description", "").lower():
            # Send as JSON
            return inputs, "application/json"
        else:
            # Send as form data
            return inputs, "application/x-www-form-urlencoded"

    # Fill template
    filled = payload_example
    for key, value in inputs.items():
        filled = filled.replace(f"{{{key}}}", str(value))

    # Try to detect format
    if filled.startswith("{") or filled.startswith("["):
        # Looks like JSON
        try:
            payload = json_lib.loads(filled)
            return payload, "application/json"
        except json_lib.JSONDecodeError:
            pass

    # Parse as form data (key=value&key=value)
    if "=" in filled and "&" in filled:
        try:
            pairs = [pair.split("=", 1) for pair in filled.split("&")]
            payload = {k: v for k, v in pairs}
            return payload, "application/x-www-form-urlencoded"
        except Exception:
            pass

    # Return as-is (likely form data string)
    return filled, None


# ============================================================================
# RESPONSE VALIDATION
# ============================================================================


def is_successful_response(response: httpx.Response) -> bool:
    """Check if HTTP response indicates success (2xx status code)"""
    return 200 <= response.status_code < 300


def validate_response(response: httpx.Response, council_name: str) -> None:
    """
    Log warnings for non-successful responses

    Note: Does not raise exceptions to maintain backwards compatibility
    """
    if response.status_code >= 500:
        logger.warning(
            f"{council_name}: Server error (HTTP {response.status_code}). "
            f"The council's server may be down or experiencing issues."
        )
    elif response.status_code >= 400:
        logger.warning(
            f"{council_name}: Client error (HTTP {response.status_code}). "
            f"Check if the provided inputs are correct."
        )
    elif response.status_code >= 300:
        logger.warning(
            f"{council_name}: Unexpected redirect (HTTP {response.status_code})."
        )


# ============================================================================
# REQUEST EXECUTORS
# ============================================================================


def execute_single_api(
    config: Dict[str, Any],
    inputs: Dict[str, Any],
    client: httpx.Client,
) -> httpx.Response:
    """Execute a single API request"""
    url_template = config["api_urls"][0]
    method = config["api_methods"][0]
    headers = prepare_headers(config)

    url = fill_url_template(url_template, inputs)

    if method == "GET":
        response = client.get(url, headers=headers)
    elif method == "POST":
        payload, content_type = prepare_payload(
            config, inputs, config.get("response_format")
        )

        # Set Content-Type if determined
        if content_type and "Content-Type" not in headers:
            headers["Content-Type"] = content_type

        # Send as JSON or form data
        if content_type == "application/json":
            response = client.post(url, headers=headers, json=payload)
        else:
            response = client.post(url, headers=headers, data=payload)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    return response


def execute_token_then_api(
    config: Dict[str, Any],
    inputs: Dict[str, Any],
    client: httpx.Client,
) -> httpx.Response:
    """Execute token retrieval, then API request with token"""
    headers = prepare_headers(config)

    # Handle single URL case (token extraction from same URL)
    if len(config.get("api_urls", [])) == 1:
        # Same URL for both steps (e.g., GET for token, POST for data)
        url = fill_url_template(config["api_urls"][0], inputs)

        # Step 1: GET to get token/session (if first method is GET)
        token_response = None
        if len(config.get("api_methods", [])) > 0 and config["api_methods"][0] == "GET":
            token_response = client.get(url, headers=headers)

        # Step 2: POST with payload (if second method is POST)
        if len(config.get("api_methods", [])) > 1 and config["api_methods"][1] == "POST":
            payload, content_type = prepare_payload(
                config, inputs, config.get("response_format")
            )

            if content_type and "Content-Type" not in headers:
                headers["Content-Type"] = content_type

            if content_type == "application/json":
                response = client.post(url, headers=headers, json=payload)
            else:
                response = client.post(url, headers=headers, data=payload)
        elif token_response:
            response = token_response
        else:
            # Fallback: just make a single POST request
            payload, content_type = prepare_payload(
                config, inputs, config.get("response_format")
            )

            if content_type and "Content-Type" not in headers:
                headers["Content-Type"] = content_type

            if content_type == "application/json":
                response = client.post(url, headers=headers, json=payload)
            else:
                response = client.post(url, headers=headers, data=payload)

        return response

    # Standard two-URL case
    if len(config.get("api_urls", [])) < 2:
        raise ValueError("token_then_api requires at least 1 URL with 2 methods, or 2 URLs")

    # Step 1: Get token/session
    token_url = fill_url_template(config["api_urls"][0], inputs)
    token_method = config["api_methods"][0]

    if token_method == "GET":
        token_response = client.get(token_url, headers=headers)
    else:
        token_response = client.post(token_url, headers=headers)

    # httpx.Client automatically maintains cookies/session

    # Step 2: Make actual API request
    api_url = fill_url_template(config["api_urls"][1], inputs)
    api_method = config["api_methods"][1]

    if api_method == "GET":
        response = client.get(api_url, headers=headers)
    else:
        payload, content_type = prepare_payload(
            config, inputs, config.get("response_format")
        )

        if content_type and "Content-Type" not in headers:
            headers["Content-Type"] = content_type

        if content_type == "application/json":
            response = client.post(api_url, headers=headers, json=payload)
        else:
            response = client.post(api_url, headers=headers, data=payload)

    return response


def execute_id_lookup_then_api(
    config: Dict[str, Any],
    inputs: Dict[str, Any],
    client: httpx.Client,
) -> httpx.Response:
    """
    Execute ID lookup from postcode, then API request with ID

    Note: ID extraction is council-specific and not yet implemented.
    This returns the lookup response for now.
    """
    if len(config.get("api_urls", [])) < 2:
        raise ValueError("id_lookup_then_api requires at least 2 URLs")

    headers = prepare_headers(config)

    # Step 1: Lookup ID from postcode
    lookup_url = fill_url_template(config["api_urls"][0], inputs)
    lookup_method = config["api_methods"][0]

    if lookup_method == "GET":
        lookup_response = client.get(lookup_url, headers=headers)
    else:
        # POST with payload
        payload, content_type = prepare_payload(
            config, inputs, config.get("response_format")
        )

        if content_type and "Content-Type" not in headers:
            headers["Content-Type"] = content_type

        if content_type == "application/json":
            lookup_response = client.post(lookup_url, headers=headers, json=payload)
        else:
            lookup_response = client.post(lookup_url, headers=headers, data=payload)

    # TODO: Extract ID from lookup response (this is council-specific)
    # For now, return the lookup response for debugging
    logger.debug(f"Lookup response status: {lookup_response.status_code}")
    logger.debug(f"Lookup response preview: {lookup_response.text[:500]}")

    # Step 2: Make API request with extracted ID
    # This would require parsing the lookup response
    # For now, just return the lookup response
    return lookup_response


# ============================================================================
# MAIN LOOKUP FUNCTION
# ============================================================================


def lookup_bin_times(
    council_name: str,
    inputs: Dict[str, Any],
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = VERIFY_SSL,
    max_retries: int = 0,
) -> httpx.Response:
    """
    Look up bin collection times for a council

    Args:
        council_name: Name of the council (matches YAML filename)
        inputs: Dictionary of required inputs (postcode, uprn, etc.)
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates (set False for councils with cert issues)
        max_retries: Number of retries for transient failures (default: 0)

    Returns:
        httpx.Response object with the result

    Raises:
        FileNotFoundError: If council config not found
        ValueError: If missing required inputs or unsupported request type
        NotImplementedError: If council requires Selenium/Playwright
        httpx.HTTPError: For network/HTTP errors
    """
    # Load council config
    config = load_council_config(council_name)

    # Validate required inputs
    required = set(config.get("required_user_input", []))
    provided = set(inputs.keys())
    missing = required - provided

    if missing:
        raise ValueError(f"Missing required inputs: {missing}")

    # Create HTTP client with session support
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        verify=verify_ssl
    ) as client:
        request_type = config.get("request_type", "")

        # Handle different request types
        if request_type == "selenium":
            raise NotImplementedError(
                f"{council_name} requires Playwright/Selenium automation. "
                f"HTTP requests not yet implemented for this council."
            )

        elif request_type == "calendar":
            raise NotImplementedError(
                f"{council_name} uses calendar request type which is not yet implemented. "
                f"This likely requires iCal/calendar file parsing."
            )

        elif request_type == "single_api":
            response = execute_single_api(config, inputs, client)
            validate_response(response, council_name)
            return response

        elif request_type == "token_then_api":
            response = execute_token_then_api(config, inputs, client)
            validate_response(response, council_name)
            return response

        elif request_type == "id_lookup_then_api":
            response = execute_id_lookup_then_api(config, inputs, client)
            validate_response(response, council_name)
            return response

        else:
            raise ValueError(
                f"Unsupported request_type: '{request_type}'. "
                f"Supported types: single_api, token_then_api, id_lookup_then_api, selenium, calendar"
            )


# ============================================================================
# ASYNC REQUEST EXECUTORS
# ============================================================================


async def execute_single_api_async(
    config: Dict[str, Any],
    inputs: Dict[str, Any],
    client: httpx.AsyncClient,
) -> httpx.Response:
    """Execute a single API request (async version)"""
    url_template = config["api_urls"][0]
    method = config["api_methods"][0]
    headers = prepare_headers(config)

    url = fill_url_template(url_template, inputs)

    if method == "GET":
        response = await client.get(url, headers=headers)
    elif method == "POST":
        payload, content_type = prepare_payload(
            config, inputs, config.get("response_format")
        )

        if content_type and "Content-Type" not in headers:
            headers["Content-Type"] = content_type

        if content_type == "application/json":
            response = await client.post(url, headers=headers, json=payload)
        else:
            response = await client.post(url, headers=headers, data=payload)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    return response


async def execute_token_then_api_async(
    config: Dict[str, Any],
    inputs: Dict[str, Any],
    client: httpx.AsyncClient,
) -> httpx.Response:
    """Execute token retrieval, then API request with token (async version)"""
    headers = prepare_headers(config)

    # Handle single URL case
    if len(config.get("api_urls", [])) == 1:
        url = fill_url_template(config["api_urls"][0], inputs)

        token_response = None
        if len(config.get("api_methods", [])) > 0 and config["api_methods"][0] == "GET":
            token_response = await client.get(url, headers=headers)

        if len(config.get("api_methods", [])) > 1 and config["api_methods"][1] == "POST":
            payload, content_type = prepare_payload(
                config, inputs, config.get("response_format")
            )

            if content_type and "Content-Type" not in headers:
                headers["Content-Type"] = content_type

            if content_type == "application/json":
                response = await client.post(url, headers=headers, json=payload)
            else:
                response = await client.post(url, headers=headers, data=payload)
        elif token_response:
            response = token_response
        else:
            payload, content_type = prepare_payload(
                config, inputs, config.get("response_format")
            )

            if content_type and "Content-Type" not in headers:
                headers["Content-Type"] = content_type

            if content_type == "application/json":
                response = await client.post(url, headers=headers, json=payload)
            else:
                response = await client.post(url, headers=headers, data=payload)

        return response

    # Standard two-URL case
    if len(config.get("api_urls", [])) < 2:
        raise ValueError("token_then_api requires at least 1 URL with 2 methods, or 2 URLs")

    # Step 1: Get token/session
    token_url = fill_url_template(config["api_urls"][0], inputs)
    token_method = config["api_methods"][0]

    if token_method == "GET":
        token_response = await client.get(token_url, headers=headers)
    else:
        token_response = await client.post(token_url, headers=headers)

    # Step 2: Make actual API request
    api_url = fill_url_template(config["api_urls"][1], inputs)
    api_method = config["api_methods"][1]

    if api_method == "GET":
        response = await client.get(api_url, headers=headers)
    else:
        payload, content_type = prepare_payload(
            config, inputs, config.get("response_format")
        )

        if content_type and "Content-Type" not in headers:
            headers["Content-Type"] = content_type

        if content_type == "application/json":
            response = await client.post(api_url, headers=headers, json=payload)
        else:
            response = await client.post(api_url, headers=headers, data=payload)

    return response


async def execute_id_lookup_then_api_async(
    config: Dict[str, Any],
    inputs: Dict[str, Any],
    client: httpx.AsyncClient,
) -> httpx.Response:
    """Execute ID lookup from postcode, then API request with ID (async version)"""
    if len(config.get("api_urls", [])) < 2:
        raise ValueError("id_lookup_then_api requires at least 2 URLs")

    headers = prepare_headers(config)

    # Step 1: Lookup ID from postcode
    lookup_url = fill_url_template(config["api_urls"][0], inputs)
    lookup_method = config["api_methods"][0]

    if lookup_method == "GET":
        lookup_response = await client.get(lookup_url, headers=headers)
    else:
        payload, content_type = prepare_payload(
            config, inputs, config.get("response_format")
        )

        if content_type and "Content-Type" not in headers:
            headers["Content-Type"] = content_type

        if content_type == "application/json":
            lookup_response = await client.post(lookup_url, headers=headers, json=payload)
        else:
            lookup_response = await client.post(lookup_url, headers=headers, data=payload)

    logger.debug(f"Lookup response status: {lookup_response.status_code}")
    logger.debug(f"Lookup response preview: {lookup_response.text[:500]}")

    return lookup_response


async def lookup_bin_times_async(
    council_name: str,
    inputs: Dict[str, Any],
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = VERIFY_SSL,
    use_requests_fallback: bool = USE_REQUESTS_FALLBACK,
) -> httpx.Response:
    """
    Look up bin collection times for a council (async version)

    Args:
        council_name: Name of the council (matches YAML filename)
        inputs: Dictionary of required inputs (postcode, uprn, etc.)
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates
        use_requests_fallback: Try requests library if httpx fails with SSL errors

    Returns:
        httpx.Response object with the result

    Raises:
        FileNotFoundError: If council config not found
        ValueError: If missing required inputs or unsupported request type
        NotImplementedError: If council requires Selenium/Playwright
        httpx.HTTPError: For network/HTTP errors
    """
    # Load council config
    config = load_council_config(council_name)

    # Validate required inputs
    required = set(config.get("required_user_input", []))
    provided = set(inputs.keys())
    missing = required - provided

    if missing:
        raise ValueError(f"Missing required inputs: {missing}")

    # Try with httpx first
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            verify=verify_ssl
        ) as client:
            request_type = config.get("request_type", "")

            # Handle different request types
            if request_type == "selenium":
                raise NotImplementedError(
                    f"{council_name} requires Playwright/Selenium automation. "
                    f"HTTP requests not yet implemented for this council."
                )

            elif request_type == "calendar":
                raise NotImplementedError(
                    f"{council_name} uses calendar request type which is not yet implemented. "
                    f"This likely requires iCal/calendar file parsing."
                )

            elif request_type == "single_api":
                response = await execute_single_api_async(config, inputs, client)
                validate_response(response, council_name)
                return response

            elif request_type == "token_then_api":
                response = await execute_token_then_api_async(config, inputs, client)
                validate_response(response, council_name)
                return response

            elif request_type == "id_lookup_then_api":
                response = await execute_id_lookup_then_api_async(config, inputs, client)
                validate_response(response, council_name)
                return response

            else:
                raise ValueError(
                    f"Unsupported request_type: '{request_type}'. "
                    f"Supported types: single_api, token_then_api, id_lookup_then_api, selenium, calendar"
                )

    except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
        # Check if it's an SSL error and we should try requests fallback
        error_str = str(e).lower()
        is_ssl_error = "ssl" in error_str or "certificate" in error_str or "tls" in error_str

        if is_ssl_error and use_requests_fallback and HAS_REQUESTS:
            logger.warning(f"{council_name}: httpx SSL error, trying requests library fallback")
            return _lookup_with_requests(council_name, config, inputs, timeout, verify_ssl)
        else:
            raise


def _lookup_with_requests(
    council_name: str,
    config: Dict[str, Any],
    inputs: Dict[str, Any],
    timeout: int,
    verify_ssl: bool
) -> httpx.Response:
    """Fallback to requests library for councils with TLS issues"""
    if not HAS_REQUESTS:
        raise ImportError("requests library not available for fallback")

    request_type = config.get("request_type", "")
    headers = prepare_headers(config)

    # Simple single_api implementation with requests
    if request_type == "single_api":
        url_template = config["api_urls"][0]
        method = config["api_methods"][0]
        url = fill_url_template(url_template, inputs)

        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
        elif method == "POST":
            payload, content_type = prepare_payload(config, inputs, config.get("response_format"))
            if content_type and "Content-Type" not in headers:
                headers["Content-Type"] = content_type

            if content_type == "application/json":
                resp = requests.post(url, headers=headers, json=payload, timeout=timeout, verify=verify_ssl)
            else:
                resp = requests.post(url, headers=headers, data=payload, timeout=timeout, verify=verify_ssl)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        # Convert requests.Response to httpx.Response-like object
        # We'll just return a minimal wrapper with the key attributes
        class RequestsResponseWrapper:
            def __init__(self, requests_response):
                self.status_code = requests_response.status_code
                self.text = requests_response.text
                self.headers = requests_response.headers
                self.content = requests_response.content

        return RequestsResponseWrapper(resp)

    else:
        raise NotImplementedError(f"requests fallback not implemented for {request_type}")


# ============================================================================
# CLI INTERFACE
# ============================================================================


def main():
    """Simple CLI for testing"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python src/bin_lookup.py <council_name> [key=value ...]")
        print("\nAvailable councils:")
        for council in list_available_councils()[:10]:
            print(f"  - {council}")
        print("  ...")
        return

    council_name = sys.argv[1]

    # Parse key=value inputs
    inputs = {}
    for arg in sys.argv[2:]:
        if "=" in arg:
            key, value = arg.split("=", 1)
            inputs[key] = value

    try:
        print(f"Looking up bin times for: {council_name}")
        print(f"Inputs: {inputs}\n")

        response = lookup_bin_times(council_name, inputs)

        print(f"Status: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        print(f"\nResponse preview:")
        print(response.text[:1000])

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
