"""
UK Council Bin Collection Scraper

A generalised scraper for extracting bin collection information from UK council
websites using pure API calls. Supports 4 distinct API patterns identified
through analysis of council website traces.
"""

import json
import re
import requests
import yaml
from typing import Dict, Any, Optional
from urllib.parse import urlparse


class BinCollectionError(Exception):
    """Base exception for bin collection scraping"""
    pass


class APIEndpointError(BinCollectionError):
    """Raised when API endpoint returns HTTP errors"""
    def __init__(self, endpoint: str, status_code: int, message: str):
        self.endpoint = endpoint
        self.status_code = status_code
        super().__init__(f"API Error {status_code} on {endpoint}: {message}")


class TokenExtractionError(BinCollectionError):
    """Raised when required tokens cannot be extracted"""
    pass


class DataValidationError(BinCollectionError):
    """Raised when API returns unexpected data format"""
    pass


class ConfigurationError(BinCollectionError):
    """Raised when council configuration is invalid"""
    pass


class BinCollectionScraper:
    """
    Generalised scraper for UK council bin collection APIs.
    
    Supports 4 API patterns:
    - REST: Direct GET requests with URL parameters
    - POST_SERVICE: JSON POST requests to service endpoints  
    - TOKEN_BASED: Extract tokens from initial requests
    - FORM_TOKEN: Extract form tokens (ViewState/CSRF)
    """
    
    def __init__(self, council_config_path: str):
        """
        Initialize scraper with council configurations.
        
        Args:
            council_config_path: Path to YAML configuration file
        """
        self.councils = self._load_council_configs(council_config_path)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_collections(self, council_name: str, postcode: str) -> Dict[str, Any]:
        """
        Get bin collection data for a postcode from specified council.
        
        Args:
            council_name: Council identifier from config
            postcode: UK postcode to lookup
            
        Returns:
            Raw API response data
            
        Raises:
            APIEndpointError: HTTP errors, 404s, connection failures
            TokenExtractionError: Cannot extract required tokens
            DataValidationError: Invalid response format
            ConfigurationError: Invalid council config
        """
        if council_name not in self.councils:
            raise ConfigurationError(f"Council '{council_name}' not found in configuration")
        
        config = self.councils[council_name]
        api_type = config.get('api_type')
        
        if api_type == 'rest':
            return self._handle_rest_api(config, postcode)
        elif api_type == 'post_service':
            return self._handle_post_service(config, postcode)
        elif api_type == 'token_based':
            return self._handle_token_api(config, postcode)
        elif api_type == 'form_token':
            return self._handle_form_token_api(config, postcode)
        else:
            raise ConfigurationError(f"Unknown api_type '{api_type}' for council '{council_name}'")
    
    def _handle_rest_api(self, config: Dict[str, Any], postcode: str) -> Dict[str, Any]:
        """
        Handle REST API pattern (Cambridge-style).
        
        Steps:
        1. GET address search endpoint with postcode
        2. GET collection data endpoint with address ID
        """
        endpoints = config.get('endpoints', {})
        
        # Step 1: Address search
        address_search_url = endpoints.get('address_search', '').format(postcode=postcode.replace(' ', ''))
        if not address_search_url:
            raise ConfigurationError("Missing 'address_search' endpoint in REST config")
        
        addresses = self._api_call('GET', address_search_url)
        
        if not addresses or len(addresses) == 0:
            raise DataValidationError(f"No addresses found for postcode {postcode}")
        
        # Step 2: Collection data
        collection_data_url = endpoints.get('collection_data', '')
        if not collection_data_url:
            raise ConfigurationError("Missing 'collection_data' endpoint in REST config")
        
        # Extract address ID (format varies by council)
        first_address = addresses[0]
        address_id = self._extract_address_id(first_address, config.get('address_id_field', 'id'))
        
        collection_url = collection_data_url.format(
            address_id=address_id,
            authority=config.get('authority_code', ''),
            **config.get('url_params', {})
        )
        
        return self._api_call('GET', collection_url)
    
    def _handle_post_service(self, config: Dict[str, Any], postcode: str) -> Dict[str, Any]:
        """
        Handle POST service API pattern (Brighton-style).
        
        Steps:
        1. Optional: GET metadata/schema endpoint
        2. POST service endpoint with JSON payload
        """
        # Optional metadata request
        metadata_endpoint = config.get('metadata_endpoint')
        if metadata_endpoint:
            self._api_call('GET', metadata_endpoint)  # May set session state
        
        # Main service request
        service_endpoint = config.get('service_endpoint')
        if not service_endpoint:
            raise ConfigurationError("Missing 'service_endpoint' in POST_SERVICE config")
        
        payload_template = config.get('payload_template', '{}')
        try:
            payload = json.loads(payload_template.format(postcode=postcode))
        except (ValueError, KeyError) as e:
            raise ConfigurationError(f"Invalid payload_template: {e}")
        
        return self._api_call('POST', service_endpoint, json=payload)
    
    def _handle_token_api(self, config: Dict[str, Any], postcode: str) -> Dict[str, Any]:
        """
        Handle token-based API pattern (Croydon-style).
        
        Steps:
        1. GET landing page to extract token
        2. POST/GET endpoint with token in URL or headers
        """
        landing_page = config.get('landing_page')
        if not landing_page:
            raise ConfigurationError("Missing 'landing_page' in TOKEN_BASED config")
        
        # Get initial page and extract token
        landing_response = self._api_call('GET', landing_page, return_text=True)
        
        token_pattern = config.get('token_pattern', '')
        if not token_pattern:
            raise ConfigurationError("Missing 'token_pattern' in TOKEN_BASED config")
        
        token = self._extract_token(landing_response, token_pattern)
        
        # Make request with token
        endpoint = config.get('endpoint', '')
        if not endpoint:
            raise ConfigurationError("Missing 'endpoint' in TOKEN_BASED config")
        
        # Format endpoint with token
        request_url = endpoint.format(token=token)
        
        # Prepare request data
        request_data = config.get('request_data', {})
        request_data[config.get('postcode_field', 'postcode')] = postcode
        
        method = config.get('method', 'POST').upper()
        if method == 'POST':
            return self._api_call('POST', request_url, data=request_data)
        else:
            return self._api_call('GET', request_url, params=request_data)
    
    def _handle_form_token_api(self, config: Dict[str, Any], postcode: str) -> Dict[str, Any]:
        """
        Handle form-token API pattern (Wigan-style).
        
        Steps:
        1. GET form page to extract ViewState/CSRF tokens
        2. POST form with tokens + postcode data
        """
        form_page = config.get('form_page')
        if not form_page:
            raise ConfigurationError("Missing 'form_page' in FORM_TOKEN config")
        
        # Get form page and extract tokens
        form_response = self._api_call('GET', form_page, return_text=True)
        
        token_patterns = config.get('token_patterns', {})
        form_tokens = {}
        
        for token_name, pattern in token_patterns.items():
            token_value = self._extract_token(form_response, pattern)
            form_tokens[token_name] = token_value
        
        # Prepare form submission
        postcode_field = config.get('postcode_field', 'postcode')
        form_data = {
            **form_tokens,
            postcode_field: postcode,
            **config.get('additional_form_data', {})
        }
        
        return self._api_call('POST', form_page, data=form_data)
    
    def _api_call(self, method: str, url: str, return_text: bool = False, **kwargs) -> Any:
        """
        Make HTTP request with comprehensive error handling.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            return_text: Return raw text instead of JSON
            **kwargs: Additional arguments for requests
            
        Returns:
            JSON data or raw text
            
        Raises:
            APIEndpointError: HTTP errors, connection issues
            DataValidationError: Invalid JSON response
        """
        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
            
            # Handle HTTP errors
            if response.status_code == 404:
                raise APIEndpointError(url, 404, "Endpoint not found - council may have changed their API")
            elif response.status_code == 403:
                raise APIEndpointError(url, 403, "Access forbidden - may need authentication token")
            elif response.status_code >= 400:
                raise APIEndpointError(url, response.status_code, response.text[:200])
            
            # Return raw text if requested (for token extraction)
            if return_text:
                return response.text
            
            # Parse JSON response
            try:
                data = response.json()
            except ValueError as e:
                raise DataValidationError(f"Invalid JSON response from {url}: {str(e)}")
            
            return data
            
        except requests.ConnectionError as e:
            raise APIEndpointError(url, 0, f"Connection failed: {str(e)}")
        except requests.Timeout as e:
            raise APIEndpointError(url, 0, f"Request timeout: {str(e)}")
    
    def _extract_token(self, text: str, pattern: str) -> str:
        """
        Extract token from text using regex pattern.
        
        Args:
            text: Source text
            pattern: Regex pattern with one capture group
            
        Returns:
            Extracted token
            
        Raises:
            TokenExtractionError: Token not found
        """
        match = re.search(pattern, text)
        if not match:
            raise TokenExtractionError(f"Could not extract token using pattern: {pattern}")
        return match.group(1)
    
    def _extract_address_id(self, address_data: Dict[str, Any], id_field: str) -> str:
        """
        Extract address ID from address data.
        
        Args:
            address_data: Address object from API
            id_field: Field name containing the ID
            
        Returns:
            Address ID
            
        Raises:
            DataValidationError: ID field not found
        """
        if id_field not in address_data:
            raise DataValidationError(f"Address ID field '{id_field}' not found in: {address_data}")
        return str(address_data[id_field])
    
    def _load_council_configs(self, config_path: str) -> Dict[str, Any]:
        """
        Load council configurations from YAML file.
        
        Args:
            config_path: Path to YAML configuration file
            
        Returns:
            Dictionary of council configurations
            
        Raises:
            ConfigurationError: File not found or invalid YAML
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                configs = yaml.safe_load(f)
            
            if not isinstance(configs, dict):
                raise ConfigurationError("Configuration must be a dictionary")
            
            # Basic validation
            for council_name, config in configs.items():
                if not isinstance(config, dict):
                    raise ConfigurationError(f"Council config for '{council_name}' must be a dictionary")
                if 'api_type' not in config:
                    raise ConfigurationError(f"Missing 'api_type' for council '{council_name}'")
            
            return configs
            
        except FileNotFoundError:
            raise ConfigurationError(f"Configuration file not found: {config_path}")
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in configuration file: {e}")