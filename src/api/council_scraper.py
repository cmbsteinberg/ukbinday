import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
import yaml
import httpx


class CouncilScraper:
    def __init__(self, config_path: str = "council_bin_config.yaml"):
        self.logger = logging.getLogger(__name__)
        self.config_path = Path(config_path)
        self.councils = {}
        self.client: Optional[httpx.AsyncClient] = None
        self._load_config()

    def _load_config(self) -> None:
        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f)

            config.pop("default_council", None)
            self.councils = config
            self.logger.info(f"Loaded config for {len(self.councils)} councils")

        except FileNotFoundError:
            self.logger.error(f"Config file not found: {self.config_path}")
            raise
        except yaml.YAMLError as e:
            self.logger.error(f"Error parsing YAML config: {e}")
            raise

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    def get_council_names(self) -> List[str]:
        return list(self.councils.keys())

    async def _get_metadata(self, council_config: Dict[str, Any]) -> Dict[str, Any]:
        metadata_endpoint = council_config.get("metadata_endpoint")
        if not metadata_endpoint:
            return {}

        try:
            self.logger.debug(f"Fetching metadata from {metadata_endpoint}")
            response = await self.client.get(metadata_endpoint)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.warning(f"Failed to fetch metadata: {e}")
            return {}

    async def _handle_auth(self, council_config: Dict[str, Any]) -> Dict[str, str]:
        auth_config = council_config.get("auth", {})
        auth_type = auth_config.get("type", "none")

        if auth_type == "none":
            return {}

        tokens = {}
        landing_page = auth_config.get("landing_page")

        if not landing_page:
            self.logger.warning("Auth required but no landing page specified")
            return {}

        try:
            self.logger.debug(f"Fetching auth tokens from {landing_page}")
            response = await self.client.get(landing_page)
            response.raise_for_status()
            content = response.text

            token_patterns = auth_config.get("token_patterns", {})
            for token_name, pattern in token_patterns.items():
                match = re.search(pattern, content)
                if match:
                    tokens[token_name] = match.group(1)
                    self.logger.debug(f"Extracted {token_name}")
                else:
                    self.logger.warning(f"Could not extract {token_name}")

            return tokens

        except httpx.HTTPError as e:
            self.logger.error(f"Auth request failed: {e}")
            return {}

    def _format_params(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        formatted = {}
        for key, value in params.items():
            if isinstance(value, str) and "{" in value:
                formatted[key] = value.format(**context)
            else:
                formatted[key] = value
        return formatted

    def _build_request_data(
        self,
        endpoint: Dict[str, Any],
        context: Dict[str, Any],
        auth_config: Dict[str, Any],
    ) -> tuple:
        url = endpoint["url"].format(**context)
        method = endpoint["method"].upper()
        params = self._format_params(endpoint.get("params", {}), context)

        # Add form_data from auth config if present
        if auth_config.get("form_data"):
            params.update(auth_config["form_data"])

        return url, method, params

    async def _make_request(
        self,
        url: str,
        method: str,
        params: Dict[str, Any],
        headers: Dict[str, str],
        payload_template: str = None,
    ) -> Any:
        try:
            if method == "GET":
                response = await self.client.get(url, params=params, headers=headers)
            elif method == "POST":
                if payload_template:
                    # Use JSON payload if template provided
                    json_data = json.loads(payload_template.format(**params))
                    response = await self.client.post(
                        url, json=json_data, headers=headers
                    )
                else:
                    # Form data
                    response = await self.client.post(url, data=params, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()

            try:
                return response.json()
            except ValueError:
                return {"raw_content": response.text}

        except httpx.HTTPError as e:
            self.logger.error(f"Request failed to {url}: {e}")
            raise

    async def search_addresses(
        self, council_name: str, postcode: str
    ) -> List[Dict[str, Any]]:
        if council_name not in self.councils:
            raise ValueError(f"Council {council_name} not found in config")

        council_config = self.councils[council_name]
        self.logger.info(
            f"Searching addresses for {council_name} with postcode {postcode}"
        )

        # Get metadata if needed
        metadata = await self._get_metadata(council_config)

        # Handle authentication
        auth_tokens = await self._handle_auth(council_config)
        auth_config = council_config.get("auth", {})

        # Build context for templating
        context = {"postcode": postcode, **auth_tokens, **metadata}

        # Get endpoint and build request
        endpoint = council_config["endpoints"]["address_search"]
        url, method, params = self._build_request_data(endpoint, context, auth_config)

        headers = council_config.get("headers", {})
        payload_template = council_config.get("payload_template")

        try:
            data = await self._make_request(
                url, method, params, headers, payload_template
            )

            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
            else:
                self.logger.warning(f"Unexpected response format: {type(data)}")
                return []

        except Exception as e:
            self.logger.error(f"Address search failed for {council_name}: {e}")
            return []

    async def get_collection_data(
        self, council_name: str, address_data: Dict[str, Any] = None, **params
    ) -> Dict[str, Any]:
        if council_name not in self.councils:
            raise ValueError(f"Council {council_name} not found in config")

        council_config = self.councils[council_name]
        collection_endpoint = council_config["endpoints"].get("collection_data")

        if not collection_endpoint:
            self.logger.warning(f"No collection data endpoint for {council_name}")
            return {}

        self.logger.info(f"Getting collection data for {council_name}")

        # Get metadata if needed
        metadata = await self._get_metadata(council_config)

        # Handle authentication
        auth_tokens = await self._handle_auth(council_config)
        auth_config = council_config.get("auth", {})

        # Build context - include address data for two-step processes
        context = {**params, **auth_tokens, **metadata}

        if address_data:
            context.update(address_data)

        # Get endpoint and build request
        url, method, request_params = self._build_request_data(
            collection_endpoint, context, auth_config
        )

        headers = council_config.get("headers", {})
        payload_template = council_config.get("payload_template")

        try:
            return await self._make_request(
                url, method, request_params, headers, payload_template
            )

        except Exception as e:
            self.logger.error(f"Collection data request failed for {council_name}: {e}")
            return {}

    def _extract_id_from_address(self, address: Dict[str, Any]) -> Dict[str, Any]:
        """Extract relevant ID fields from address for collection lookup"""
        id_fields = {}

        # Common ID field names
        for field in ["address_id", "uprn", "id", "address", "Seq", "PC"]:
            if field in address:
                id_fields[field] = address[field]

        return id_fields

    async def scrape_council(self, council_name: str, postcode: str) -> Dict[str, Any]:
        self.logger.info(f"Starting scrape for {council_name} with postcode {postcode}")

        try:
            # Search for addresses
            addresses = await self.search_addresses(council_name, postcode)

            if not addresses:
                return {
                    "error": "No addresses found",
                    "council": council_name,
                    "postcode": postcode,
                }

            result = {
                "council": council_name,
                "postcode": postcode,
                "addresses": addresses,
            }

            # If we have collection data endpoint, get collection info
            council_config = self.councils[council_name]
            if "collection_data" in council_config["endpoints"]:
                first_address = addresses[0]
                id_params = self._extract_id_from_address(first_address)

                collection_data = await self.get_collection_data(
                    council_name, address_data=first_address, **id_params
                )

                result["collection_data"] = collection_data

            return result

        except Exception as e:
            self.logger.error(f"Scrape failed for {council_name}: {e}")
            return {"error": str(e), "council": council_name, "postcode": postcode}


async def main():
    logging.basicConfig(level=logging.INFO)

    async with CouncilScraper("council_bin_config.yaml") as scraper:
        print("Available councils:", scraper.get_council_names())

        # Test different patterns
        councils_to_test = [
            "cambridge_city_council",  # Pattern 1: REST API
            "brighton_and_hove_city_council",  # Pattern 2: POST with metadata/payload
            "london_borough_of_croydon",  # Pattern 3: Token auth
            "wigan_metropolitan_borough_council",  # Pattern 4: Form tokens
        ]

        for council in councils_to_test:
            if council in scraper.get_council_names():
                print(f"\n--- Testing {council} ---")
                result = await scraper.scrape_council(council, "CB1 1AA")
                print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
