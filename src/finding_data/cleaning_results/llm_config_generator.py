"""
LLM-powered council bin configuration generator.

This module uses an LLM to analyze council scraping traces and generate
configuration entries for council_bin_config.yaml.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional, Union
from dotenv import load_dotenv
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, validator
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.settings import ModelSettings

# Load environment variables for Google credentials
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AuthType(str, Enum):
    """Supported authentication types."""

    NONE = "none"
    TOKEN = "token"
    FORM_TOKEN = "form_token"


class HttpMethod(str, Enum):
    """Supported HTTP methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


class AuthConfig(BaseModel):
    """Authentication configuration for council APIs."""

    type: AuthType = AuthType.NONE
    landing_page: Optional[HttpUrl] = None
    token_patterns: dict[str, str] = Field(default_factory=dict)
    form_data: dict[str, str] = Field(default_factory=dict)

    @validator("landing_page")
    def landing_page_required_for_auth(cls, v, values):
        """Validate that landing_page is provided when auth type requires it."""
        auth_type = values.get("type")
        if auth_type in [AuthType.TOKEN, AuthType.FORM_TOKEN] and not v:
            raise ValueError(
                f"landing_page is required when auth type is '{auth_type.value}'"
            )
        return v

    @validator("token_patterns")
    def token_patterns_required_for_auth(cls, v, values):
        """Validate that token_patterns are provided when auth type requires them."""
        auth_type = values.get("type")
        if auth_type in [AuthType.TOKEN, AuthType.FORM_TOKEN] and not v:
            raise ValueError(
                f"token_patterns are required when auth type is '{auth_type.value}'"
            )
        return v


class EndpointConfig(BaseModel):
    """API endpoint configuration."""

    url: HttpUrl
    method: HttpMethod = HttpMethod.GET
    params: dict[str, Union[str, int]] = Field(default_factory=dict)

    @validator("params")
    def validate_params(cls, v):
        """Ensure all param values are strings or integers."""
        for key, value in v.items():
            if not isinstance(value, (str, int)):
                raise ValueError(
                    f"Parameter '{key}' must be a string or integer, got {type(value)}"
                )
        return v


class EndpointsConfig(BaseModel):
    """Collection of endpoints for a council."""

    address_search: EndpointConfig
    collection_data: Optional[EndpointConfig] = None

    @validator("collection_data")
    def collection_data_validation(cls, v, values):
        """Add any cross-endpoint validation if needed."""
        # Could add validation here, e.g., ensuring collection_data URL is compatible
        # with address_search results
        return v


class CouncilConfig(BaseModel):
    """Complete configuration for a council bin collection API."""

    name: str = Field(..., min_length=1, description="Council name")
    auth: AuthConfig = Field(default_factory=AuthConfig)
    endpoints: EndpointsConfig
    headers: dict[str, str] = Field(default_factory=dict)
    metadata_endpoint: Optional[HttpUrl] = None
    payload_template: Optional[str] = None

    @validator("name")
    def name_not_empty(cls, v):
        """Ensure name is not empty or just whitespace."""
        if not v or not v.strip():
            raise ValueError("Council name cannot be empty")
        return v.strip()

    @validator("payload_template")
    def payload_template_for_post(cls, v, values):
        """Validate payload template is provided for POST endpoints if needed."""
        endpoints = values.get("endpoints")
        if endpoints and hasattr(endpoints, "address_search"):
            if endpoints.address_search.method == HttpMethod.POST and not v:
                # This is a warning rather than an error, as some POST endpoints
                # might use form data instead of JSON payload
                pass
        return v

    class Config:
        """Pydantic model configuration."""

        use_enum_values = True
        validate_assignment = True
        extra = "forbid"  # Prevent additional fields not defined in the model


class ConfigGenerationResult(BaseModel):
    """Result of config generation attempt."""

    council_name: str
    success: bool
    config: Optional[CouncilConfig] = None
    error: Optional[str] = None
    error_type: Optional[str] = (
        None  # 'missing_files', 'unsuccessful_scraping', 'llm_error', 'parsing_error'
    )


# System prompt for the LLM
SYSTEM_PROMPT = """
You are an expert API analyst who specializes in reverse engineering web scraping traces 
to understand how council bin collection websites work. Your task is to analyze council 
scraping data and extract the API configuration needed to programmatically retrieve 
bin collection information.

You will be provided with:
1. reduced_results.json - Contains the final structured output from scraping
2. trace.json - Contains detailed workflow steps, navigation events, and API calls made during scraping

From this data, you need to determine:
- The API endpoints used for address search and collection data
- Authentication requirements (tokens, form data, etc.)
- HTTP methods and parameters
- Any special headers or payload templates needed

Generate a complete configuration that follows the existing patterns in council_bin_config.yaml.

Focus on identifying:
1. Authentication patterns (none, token, form_token)
2. API endpoint URLs and methods
3. Required parameters and their placeholder names (like {postcode}, {address_id})
4. Any special headers or payload formatting
5. Two-step processes (address search → collection data lookup)

Be precise about parameter names and URL patterns. Use standard placeholder names like:
- {postcode} for postcode parameters  
- {address_id}, {uprn}, {id} for address identifiers
- {webpage_token} for webpage tokens
- Standard form field names like __VIEWSTATE, __EVENTVALIDATION for ASP.NET forms

IMPORTANT: If the scraping was unsuccessful (indicated by error messages in the data or 
incomplete results), respond with an error explanation instead of attempting to generate 
a configuration.
"""


def create_agent() -> Agent:
    """Create and configure the LLM agent for config generation."""
    provider = GoogleProvider(
        location="global",
        vertexai=True,
    )

    model = GoogleModel(
        "gemini-2.5-flash",
        provider=provider,
    )

    # Create agent with structured output and temperature settings
    agent = Agent(
        model,
        output_type=CouncilConfig,
        system_prompt=SYSTEM_PROMPT,
        model_settings=ModelSettings(temperature=0.1),
    )

    return agent


async def load_council_data(council_dir: Path) -> dict[str, Any]:
    """Load reduced_results.json and trace.json for a council."""
    reduced_results_file = council_dir / "reduced_results.json"
    trace_file = council_dir / "trace.json"

    if not reduced_results_file.exists() or not trace_file.exists():
        raise FileNotFoundError(f"Missing required files in {council_dir}")

    with open(reduced_results_file, "r") as f:
        reduced_results = json.load(f)

    with open(trace_file, "r") as f:
        trace_data = json.load(f)

    return {
        "reduced_results": reduced_results,
        "trace": trace_data,
        "council_name": council_dir.name,
    }


def check_scraping_success(council_data: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Check if the scraping was successful based on the data."""
    reduced_results = council_data["reduced_results"]

    # Check for explicit error in reduced_results
    if "output" in reduced_results and isinstance(reduced_results["output"], dict):
        if "error" in reduced_results["output"]:
            return False, f"Scraping failed: {reduced_results['output']['error']}"

    # Check if we have valid output data
    if "output" in reduced_results:
        output = reduced_results["output"]
        if isinstance(output, dict):
            # Check if we have bin collection data
            required_fields = [
                "general_waste",
                "recycling",
                "food_waste",
                "garden_waste",
            ]
            if any(field in output for field in required_fields):
                # Check if any of the bin data has actual information
                for field in required_fields:
                    if (
                        field in output
                        and output[field]
                        and isinstance(output[field], dict)
                    ):
                        if output[field].get("next_pickup_day") or output[field].get(
                            "frequency"
                        ):
                            return True, None

        # If output exists but doesn't contain meaningful bin data
        return False, "Scraping completed but no meaningful bin collection data found"

    return False, "No output data found in reduced_results"


def check_council_already_processed(council_dir: Path) -> bool:
    """Check if a council has already been processed by looking for generated_config.json."""
    generated_config_file = council_dir / "generated_config.json"
    return generated_config_file.exists()


async def generate_council_config(
    agent: Agent, council_data: dict[str, Any]
) -> CouncilConfig:
    """Generate configuration for a single council using the LLM."""
    council_name = council_data["council_name"]

    prompt = f"""
Analyze the following council scraping data and generate the API configuration:

Council: {council_name}

=== REDUCED RESULTS ===
{json.dumps(council_data["reduced_results"], indent=2)}

=== TRACE DATA ===
{json.dumps(council_data["trace"], indent=2)}

Based on this data, determine the API endpoints, authentication requirements, 
and parameters needed to programmatically retrieve bin collection information 
for this council. Focus on the actual API calls made during scraping, not the 
browser automation steps.

Generate a complete CouncilConfig that can be used to recreate the same API calls 
programmatically.
"""

    logger.info(f"Generating config for {council_name}")

    try:
        # Use run with the agent (run method is async by default)
        result = await agent.run(
            prompt,
            model_settings=ModelSettings(
                temperature=0.0
            ),  # Override for maximum determinism
        )
        return result.output
    except Exception as e:
        logger.error(f"Failed to generate config for {council_name}: {e}")
        raise


async def llm_call(
    traces_dir: Path, council_name: str, semaphore: asyncio.Semaphore
) -> ConfigGenerationResult:
    """Generate configuration for a single council."""
    council_dir = traces_dir / council_name

    async with semaphore:
        try:
            # Load council data
            try:
                council_data = await load_council_data(council_dir)
            except FileNotFoundError as e:
                return ConfigGenerationResult(
                    council_name=council_name,
                    success=False,
                    error=str(e),
                    error_type="missing_files",
                )

            # Check if scraping was successful
            success, error_msg = check_scraping_success(council_data)
            if not success:
                return ConfigGenerationResult(
                    council_name=council_name,
                    success=False,
                    error=error_msg,
                    error_type="unsuccessful_scraping",
                )

            # Generate config using LLM agent
            agent = create_agent()
            try:
                config = await generate_council_config(agent, council_data)

                result = ConfigGenerationResult(
                    council_name=council_name, success=True, config=config
                )

                # Also save the result
                result_file = council_dir / "generated_config.json"
                with open(result_file, "w") as f:
                    f.write(config.model_dump_json())

                return result

            except Exception as e:
                return ConfigGenerationResult(
                    council_name=council_name,
                    success=False,
                    error=str(e),
                    error_type="llm_error",
                )

        except Exception as e:
            return ConfigGenerationResult(
                council_name=council_name,
                success=False,
                error=str(e),
                error_type="parsing_error",
            )


async def for_all_councils(
    traces_dir: Path = None,
    max_concurrent: int = 5,
) -> dict[str, ConfigGenerationResult]:
    """Generate configurations for all councils in the traces directory."""
    if traces_dir is None:
        traces_dir = Path("data/traces")

    traces_dir = Path(traces_dir)
    if not traces_dir.exists():
        raise FileNotFoundError(f"Traces directory not found: {traces_dir}")

    # Get all council directories
    all_council_dirs = [d for d in traces_dir.iterdir() if d.is_dir()]
    logger.info(f"Found {len(all_council_dirs)} council directories")

    # Filter out councils that have already been processed
    council_dirs = []
    skipped_count = 0
    for council_dir in all_council_dirs:
        if check_council_already_processed(council_dir):
            skipped_count += 1
            logger.info(f"Skipping {council_dir.name} - already processed")
        else:
            council_dirs.append(council_dir)

    logger.info(
        f"Processing {len(council_dirs)} councils ({skipped_count} already processed)"
    )

    if not council_dirs:
        logger.info("No councils to process")
        return {}

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_concurrent)

    results = {}

    # Create tasks for all councils
    tasks = [
        llm_call(traces_dir, council_dir.name, semaphore)
        for council_dir in council_dirs
    ]

    # Execute all tasks with progress logging
    logger.info(f"Starting processing with max {max_concurrent} concurrent requests")
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    for council_dir, result in zip(council_dirs, batch_results):
        council_name = council_dir.name
        if isinstance(result, Exception):
            results[council_name] = ConfigGenerationResult(
                council_name=council_name,
                success=False,
                error=str(result),
                error_type="processing_error",
            )
        else:
            results[council_name] = result

    # Summary statistics
    successful = sum(1 for r in results.values() if r.success)
    failed = len(results) - successful

    logger.info(f"Config generation complete: {successful} successful, {failed} failed")

    # Print error summary
    error_types = {}
    for result in results.values():
        if not result.success:
            error_type = result.error_type or "unknown"
            error_types[error_type] = error_types.get(error_type, 0) + 1

    if error_types:
        logger.info("Error breakdown:")
        for error_type, count in error_types.items():
            logger.info(f"  {error_type}: {count}")

    return results


if __name__ == "__main__":
    asyncio.run(for_all_councils(traces_dir=Path("data/traces"), max_concurrent=20))
