import yaml
import httpx
import json as json_lib
from pathlib import Path
from typing import Any, Awaitable, Dict, Optional, Tuple, Union
import logging
import time
import requests

from .utils import (
    extract_headers_from_description,
    fill_url_template,
)
from .exceptions import ConfigError

HAS_REQUESTS = True


# ============================================================================
# CONFIGURATION
# ============================================================================

COUNCILS_DIR = Path("extraction/data/councils")
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DEFAULT_TIMEOUT = 30
VERIFY_SSL = (
    True  # Set to False to disable SSL verification for councils with cert issues
)
USE_REQUESTS_FALLBACK = True  # Try requests library if httpx fails with SSL errors

# Setup logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)


class BinLookup:
    """
    Bin collection time lookup service

    Handles loading council configurations, executing HTTP requests,
    and managing retries and error handling.
    """

    def __init__(
        self,
        councils_dir: Path = COUNCILS_DIR,
        timeout: int = DEFAULT_TIMEOUT,
        verify_ssl: bool = VERIFY_SSL,
        use_requests_fallback: bool = USE_REQUESTS_FALLBACK,
        max_retries: int = 0,
    ):
        """
        Initialize BinLookup service

        Args:
            councils_dir: Directory containing council YAML configs
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
            use_requests_fallback: Try requests library if httpx fails with SSL errors
            max_retries: Number of retries for transient failures
        """
        self.councils_dir = councils_dir
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.use_requests_fallback = use_requests_fallback
        self.max_retries = max_retries

    # ========================================================================
    # CONFIG MANAGEMENT
    # ========================================================================

    def load_council_config(self, council_name: str) -> Dict[str, Any]:
        """Load YAML config for a specific council"""
        yaml_file = self.councils_dir / f"{council_name}.yaml"

        if not yaml_file.exists():
            raise FileNotFoundError(f"No config found for council: {council_name}")

        with open(yaml_file, "r") as f:
            return yaml.safe_load(f)

    def validate_council_config(
        self, config: Dict[str, Any], council_name: str
    ) -> None:
        """
        Validate council config before execution

        Raises:
            ConfigError: If config is invalid
        """
        request_type = config.get("request_type", "")
        api_urls = config.get("api_urls", [])
        api_methods = config.get("api_methods", [])

        # Check id_lookup_then_api has at least 2 URLs
        if request_type == "id_lookup_then_api":
            if not api_urls or len(api_urls) < 2:
                raise ConfigError(
                    f"{council_name}: id_lookup_then_api requires at least 2 URLs "
                    f"(got {len(api_urls)}). Config needs updating."
                )

        # Check single_api/token_then_api has at least 1 URL
        if request_type in ["single_api", "token_then_api"]:
            if not api_urls or len(api_urls) < 1:
                raise ConfigError(
                    f"{council_name}: {request_type} requires at least 1 URL "
                    f"(got {len(api_urls)}). Config needs updating."
                )

        # Check methods match URLs count
        if api_urls and api_methods:
            if len(api_methods) < len(api_urls):
                raise ConfigError(
                    f"{council_name}: Mismatch between URLs ({len(api_urls)}) "
                    f"and methods ({len(api_methods)}). Config needs updating."
                )

    def validate_inputs(self, config: Dict[str, Any], inputs: Dict[str, Any]) -> None:
        """
        Validate required inputs are provided

        Raises:
            ValueError: If required inputs are missing
        """
        required = set(config.get("required_user_input", []))
        provided = set(inputs.keys())
        missing = required - provided

        if missing:
            raise ValueError(f"Missing required inputs: {missing}")

    # ========================================================================
    # REQUEST PREPARATION
    # ========================================================================

    def prepare_headers(self, config: Dict[str, Any]) -> Dict[str, str]:
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

    def prepare_payload(
        self,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
        response_format: Optional[str] = None,
    ) -> Tuple[Any, Optional[str]]:
        """
        Prepare payload for POST request

        Returns:
            Tuple of (payload, content_type)
        """
        payload_example = config.get("api_payload_example")

        if not payload_example:
            # Try to infer from response_format and inputs
            if (
                response_format == "json"
                or "json" in config.get("api_description", "").lower()
            ):
                return inputs, "application/json"
            else:
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

    # ========================================================================
    # RESPONSE HANDLING
    # ========================================================================

    def is_successful_response(self, response: httpx.Response) -> bool:
        """Check if HTTP response indicates success (2xx status code)"""
        return 200 <= response.status_code < 300

    def validate_response(self, response: httpx.Response, council_name: str) -> None:
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

    # ========================================================================
    # HTTP REQUEST EXECUTION (Unified methods to reduce duplication)
    # ========================================================================

    def _execute_http_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        client: Union[httpx.Client, httpx.AsyncClient],
        payload: Optional[Any] = None,
        content_type: Optional[str] = None,
    ) -> Union[httpx.Response, Awaitable[httpx.Response]]:
        """
        Unified HTTP request execution for both sync and async

        Reduces duplication by handling GET/POST logic in one place
        """
        if method == "GET":
            return client.get(url, headers=headers)
        elif method == "POST":
            # Set Content-Type if determined
            if content_type and "Content-Type" not in headers:
                headers = {**headers, "Content-Type": content_type}

            # Send as JSON or form data
            if content_type == "application/json":
                return client.post(url, headers=headers, json=payload)
            else:
                return client.post(url, headers=headers, data=payload)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

    # ========================================================================
    # REQUEST EXECUTORS (Sync)
    # ========================================================================

    def execute_single_api(
        self,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
        client: httpx.Client,
        council_name: str = "Unknown",
    ) -> httpx.Response:
        """Execute a single API request"""
        api_urls = config.get("api_urls", [])
        api_methods = config.get("api_methods", [])

        if not api_urls or len(api_urls) < 1:
            raise ValueError(f"{council_name}: No API URLs defined in config")
        if not api_methods or len(api_methods) < 1:
            raise ValueError(f"{council_name}: No API methods defined in config")

        url_template = api_urls[0]
        method = api_methods[0]
        headers = self.prepare_headers(config)
        url = fill_url_template(url_template, inputs)

        logger.debug(f"{council_name}: Requesting {method} {url}")

        if method == "POST":
            payload, content_type = self.prepare_payload(
                config, inputs, config.get("response_format")
            )
            response = self._execute_http_request(
                method, url, headers, client, payload, content_type
            )
        else:
            response = self._execute_http_request(method, url, headers, client)

        logger.debug(f"{council_name}: Response status {response.status_code}")
        return response

    def execute_token_then_api(
        self,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
        client: httpx.Client,
    ) -> httpx.Response:
        """Execute token retrieval, then API request with token"""
        headers = self.prepare_headers(config)

        # Handle single URL case (token extraction from same URL)
        if len(config.get("api_urls", [])) == 1:
            url = fill_url_template(config["api_urls"][0], inputs)

            # Step 1: GET to get token/session (if first method is GET)
            token_response = None
            if (
                len(config.get("api_methods", [])) > 0
                and config["api_methods"][0] == "GET"
            ):
                token_response = client.get(url, headers=headers)

            # Step 2: POST with payload (if second method is POST)
            if (
                len(config.get("api_methods", [])) > 1
                and config["api_methods"][1] == "POST"
            ):
                payload, content_type = self.prepare_payload(
                    config, inputs, config.get("response_format")
                )
                response = self._execute_http_request(
                    "POST", url, headers, client, payload, content_type
                )
            elif token_response:
                response = token_response
            else:
                # Fallback: just make a single POST request
                payload, content_type = self.prepare_payload(
                    config, inputs, config.get("response_format")
                )
                response = self._execute_http_request(
                    "POST", url, headers, client, payload, content_type
                )

            return response

        # Standard two-URL case
        if len(config.get("api_urls", [])) < 2:
            raise ValueError(
                "token_then_api requires at least 1 URL with 2 methods, or 2 URLs"
            )

        # Step 1: Get token/session
        token_url = fill_url_template(config["api_urls"][0], inputs)
        token_method = config["api_methods"][0]
        token_response = self._execute_http_request(
            token_method, token_url, headers, client
        )

        # Step 2: Make actual API request
        api_url = fill_url_template(config["api_urls"][1], inputs)
        api_method = config["api_methods"][1]

        if api_method == "POST":
            payload, content_type = self.prepare_payload(
                config, inputs, config.get("response_format")
            )
            response = self._execute_http_request(
                api_method, api_url, headers, client, payload, content_type
            )
        else:
            response = self._execute_http_request(api_method, api_url, headers, client)

        return response

    def execute_id_lookup_then_api(
        self,
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

        headers = self.prepare_headers(config)

        # Step 1: Lookup ID from postcode
        lookup_url = fill_url_template(config["api_urls"][0], inputs)
        lookup_method = config["api_methods"][0]

        if lookup_method == "POST":
            payload, content_type = self.prepare_payload(
                config, inputs, config.get("response_format")
            )
            lookup_response = self._execute_http_request(
                lookup_method, lookup_url, headers, client, payload, content_type
            )
        else:
            lookup_response = self._execute_http_request(
                lookup_method, lookup_url, headers, client
            )

        # TODO: Extract ID from lookup response (this is council-specific)
        logger.debug(f"Lookup response status: {lookup_response.status_code}")
        logger.debug(f"Lookup response preview: {lookup_response.text[:500]}")

        return lookup_response

    # ========================================================================
    # REQUEST EXECUTORS (Async)
    # ========================================================================

    async def execute_single_api_async(
        self,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
        client: httpx.AsyncClient,
        council_name: str = "Unknown",
    ) -> httpx.Response:
        """Execute a single API request (async version)"""
        api_urls = config.get("api_urls", [])
        api_methods = config.get("api_methods", [])

        if not api_urls or len(api_urls) < 1:
            raise ValueError(f"{council_name}: No API URLs defined in config")
        if not api_methods or len(api_methods) < 1:
            raise ValueError(f"{council_name}: No API methods defined in config")

        url_template = api_urls[0]
        method = api_methods[0]
        headers = self.prepare_headers(config)
        url = fill_url_template(url_template, inputs)

        logger.debug(f"{council_name}: Requesting {method} {url}")

        if method == "POST":
            payload, content_type = self.prepare_payload(
                config, inputs, config.get("response_format")
            )
            response = await self._execute_http_request(
                method, url, headers, client, payload, content_type
            )
        else:
            response = await self._execute_http_request(method, url, headers, client)

        logger.debug(f"{council_name}: Response status {response.status_code}")
        return response

    async def execute_token_then_api_async(
        self,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
        client: httpx.AsyncClient,
    ) -> httpx.Response:
        """Execute token retrieval, then API request with token (async version)"""
        headers = self.prepare_headers(config)

        # Handle single URL case
        if len(config.get("api_urls", [])) == 1:
            url = fill_url_template(config["api_urls"][0], inputs)

            token_response = None
            if (
                len(config.get("api_methods", [])) > 0
                and config["api_methods"][0] == "GET"
            ):
                token_response = await client.get(url, headers=headers)

            if (
                len(config.get("api_methods", [])) > 1
                and config["api_methods"][1] == "POST"
            ):
                payload, content_type = self.prepare_payload(
                    config, inputs, config.get("response_format")
                )
                response = await self._execute_http_request(
                    "POST", url, headers, client, payload, content_type
                )
            elif token_response:
                response = token_response
            else:
                payload, content_type = self.prepare_payload(
                    config, inputs, config.get("response_format")
                )
                response = await self._execute_http_request(
                    "POST", url, headers, client, payload, content_type
                )

            return response

        # Standard two-URL case
        if len(config.get("api_urls", [])) < 2:
            raise ValueError(
                "token_then_api requires at least 1 URL with 2 methods, or 2 URLs"
            )

        # Step 1: Get token/session
        token_url = fill_url_template(config["api_urls"][0], inputs)
        token_method = config["api_methods"][0]
        token_response = await self._execute_http_request(
            token_method, token_url, headers, client
        )

        # Step 2: Make actual API request
        api_url = fill_url_template(config["api_urls"][1], inputs)
        api_method = config["api_methods"][1]

        if api_method == "POST":
            payload, content_type = self.prepare_payload(
                config, inputs, config.get("response_format")
            )
            response = await self._execute_http_request(
                api_method, api_url, headers, client, payload, content_type
            )
        else:
            response = await self._execute_http_request(
                api_method, api_url, headers, client
            )

        return response

    async def execute_id_lookup_then_api_async(
        self,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
        client: httpx.AsyncClient,
    ) -> httpx.Response:
        """Execute ID lookup from postcode, then API request with ID (async version)"""
        if len(config.get("api_urls", [])) < 2:
            raise ValueError("id_lookup_then_api requires at least 2 URLs")

        headers = self.prepare_headers(config)

        # Step 1: Lookup ID from postcode
        lookup_url = fill_url_template(config["api_urls"][0], inputs)
        lookup_method = config["api_methods"][0]

        if lookup_method == "POST":
            payload, content_type = self.prepare_payload(
                config, inputs, config.get("response_format")
            )
            lookup_response = await self._execute_http_request(
                lookup_method, lookup_url, headers, client, payload, content_type
            )
        else:
            lookup_response = await self._execute_http_request(
                lookup_method, lookup_url, headers, client
            )

        logger.debug(f"Lookup response status: {lookup_response.status_code}")
        logger.debug(f"Lookup response preview: {lookup_response.text[:500]}")

        return lookup_response

    # ========================================================================
    # ERROR HANDLING (Centralized)
    # ========================================================================

    def _should_retry(self, exception: Exception, attempt: int) -> bool:
        """
        Determine if request should be retried

        Returns:
            True if retry should be attempted, False otherwise
        """
        if attempt >= self.max_retries:
            return False

        # Retry on timeout errors
        if isinstance(exception, (httpx.TimeoutException, httpx.ReadTimeout)):
            return True

        # Retry on server errors (5xx) but not client errors (4xx)
        if isinstance(exception, httpx.HTTPStatusError):
            return exception.response.status_code >= 500

        return False

    def _handle_retry(
        self, exception: Exception, council_name: str, attempt: int
    ) -> None:
        """
        Handle retry logic including backoff and logging

        Args:
            exception: The exception that triggered retry
            council_name: Name of the council (for logging)
            attempt: Current attempt number (0-indexed)
        """
        wait_time = 2**attempt  # Exponential backoff

        if isinstance(exception, (httpx.TimeoutException, httpx.ReadTimeout)):
            logger.warning(
                f"{council_name}: Timeout on attempt {attempt + 1}/{self.max_retries + 1}, "
                f"retrying in {wait_time}s..."
            )
        elif isinstance(exception, httpx.HTTPStatusError):
            logger.warning(
                f"{council_name}: Server error {exception.response.status_code} on attempt "
                f"{attempt + 1}/{self.max_retries + 1}, retrying in {wait_time}s..."
            )

        time.sleep(wait_time)

    def _handle_ssl_error(
        self,
        exception: Exception,
        council_name: str,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
    ) -> httpx.Response:
        """
        Handle SSL errors with requests library fallback

        Returns:
            Response from requests library fallback

        Raises:
            Original exception if fallback not available or not SSL error
        """
        error_str = str(exception).lower()
        is_ssl_error = (
            "ssl" in error_str or "certificate" in error_str or "tls" in error_str
        )

        if is_ssl_error and self.use_requests_fallback and HAS_REQUESTS:
            logger.warning(
                f"{council_name}: httpx SSL error, trying requests library fallback"
            )
            return self._lookup_with_requests(council_name, config, inputs)
        else:
            raise

    def _lookup_with_requests(
        self,
        council_name: str,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
    ) -> httpx.Response:
        """Fallback to requests library for councils with TLS issues"""
        if not HAS_REQUESTS:
            raise ImportError("requests library not available for fallback")

        request_type = config.get("request_type", "")
        headers = self.prepare_headers(config)

        # Simple single_api implementation with requests
        if request_type == "single_api":
            url_template = config["api_urls"][0]
            method = config["api_methods"][0]
            url = fill_url_template(url_template, inputs)

            if method == "GET":
                resp = requests.get(
                    url, headers=headers, timeout=self.timeout, verify=self.verify_ssl
                )
            elif method == "POST":
                payload, content_type = self.prepare_payload(
                    config, inputs, config.get("response_format")
                )
                if content_type and "Content-Type" not in headers:
                    headers["Content-Type"] = content_type

                if content_type == "application/json":
                    resp = requests.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=self.timeout,
                        verify=self.verify_ssl,
                    )
                else:
                    resp = requests.post(
                        url,
                        headers=headers,
                        data=payload,
                        timeout=self.timeout,
                        verify=self.verify_ssl,
                    )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # Convert requests.Response to httpx.Response-like object
            class RequestsResponseWrapper:
                def __init__(self, requests_response):
                    self.status_code = requests_response.status_code
                    self.text = requests_response.text
                    self.headers = requests_response.headers
                    self.content = requests_response.content

            return RequestsResponseWrapper(resp)
        else:
            raise NotImplementedError(
                f"requests fallback not implemented for {request_type}"
            )

    # ========================================================================
    # MAIN LOOKUP METHODS
    # ========================================================================

    def lookup(
        self,
        council_name: str,
        inputs: Dict[str, Any],
    ) -> httpx.Response:
        """
        Look up bin collection times for a council

        Args:
            council_name: Name of the council (matches YAML filename)
            inputs: Dictionary of required inputs (postcode, uprn, etc.)

        Returns:
            httpx.Response object with the result

        Raises:
            FileNotFoundError: If council config not found
            ValueError: If missing required inputs or unsupported request type
            NotImplementedError: If council requires Selenium/Playwright
            httpx.HTTPError: For network/HTTP errors
        """
        # Load and validate council config
        config = self.load_council_config(council_name)
        self.validate_council_config(config, council_name)
        self.validate_inputs(config, inputs)

        # Retry logic
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                # Create HTTP client with session support
                with httpx.Client(
                    timeout=self.timeout, follow_redirects=True, verify=self.verify_ssl
                ) as client:
                    return self._execute_request_type(
                        config, inputs, client, council_name
                    )

            except (
                httpx.TimeoutException,
                httpx.ReadTimeout,
                httpx.HTTPStatusError,
            ) as e:
                last_exception = e
                if self._should_retry(e, attempt):
                    self._handle_retry(e, council_name, attempt)
                else:
                    if isinstance(e, (httpx.TimeoutException, httpx.ReadTimeout)):
                        logger.error(
                            f"{council_name}: Timeout after {self.max_retries + 1} attempts"
                        )
                    raise

        # If we get here, all retries failed
        if last_exception:
            raise last_exception

    async def lookup_async(
        self,
        council_name: str,
        inputs: Dict[str, Any],
    ) -> httpx.Response:
        """
        Look up bin collection times for a council (async version)

        Args:
            council_name: Name of the council (matches YAML filename)
            inputs: Dictionary of required inputs (postcode, uprn, etc.)

        Returns:
            httpx.Response object with the result

        Raises:
            FileNotFoundError: If council config not found
            ValueError: If missing required inputs or unsupported request type
            NotImplementedError: If council requires Selenium/Playwright
            httpx.HTTPError: For network/HTTP errors
        """
        # Load and validate council config
        config = self.load_council_config(council_name)
        self.validate_council_config(config, council_name)
        self.validate_inputs(config, inputs)

        # Try with httpx
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True, verify=self.verify_ssl
            ) as client:
                return await self._execute_request_type_async(
                    config, inputs, client, council_name
                )

        except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
            return self._handle_ssl_error(e, council_name, config, inputs)

    def _execute_request_type(
        self,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
        client: httpx.Client,
        council_name: str,
    ) -> httpx.Response:
        """Execute request based on request_type"""
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
            response = self.execute_single_api(config, inputs, client, council_name)
            self.validate_response(response, council_name)
            return response

        elif request_type == "token_then_api":
            response = self.execute_token_then_api(config, inputs, client)
            self.validate_response(response, council_name)
            return response

        elif request_type == "id_lookup_then_api":
            response = self.execute_id_lookup_then_api(config, inputs, client)
            self.validate_response(response, council_name)
            return response

        else:
            raise ValueError(
                f"Unsupported request_type: '{request_type}'. "
                f"Supported types: single_api, token_then_api, id_lookup_then_api, selenium, calendar"
            )

    async def _execute_request_type_async(
        self,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
        client: httpx.AsyncClient,
        council_name: str,
    ) -> httpx.Response:
        """Execute request based on request_type (async version)"""
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
            response = await self.execute_single_api_async(
                config, inputs, client, council_name
            )
            self.validate_response(response, council_name)
            return response

        elif request_type == "token_then_api":
            response = await self.execute_token_then_api_async(config, inputs, client)
            self.validate_response(response, council_name)
            return response

        elif request_type == "id_lookup_then_api":
            response = await self.execute_id_lookup_then_api_async(
                config, inputs, client
            )
            self.validate_response(response, council_name)
            return response

        else:
            raise ValueError(
                f"Unsupported request_type: '{request_type}'. "
                f"Supported types: single_api, token_then_api, id_lookup_then_api, selenium, calendar"
            )