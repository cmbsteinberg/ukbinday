import re
from typing import Any
from pathlib import Path


def extract_headers_from_description(description: str) -> dict[str, str]:
    """Extract API keys and headers mentioned in the description"""
    headers = {}

    # Extract Ocp-Apim-Subscription-Key
    ocp_match = re.search(
        r"Ocp-Apim-Subscription-Key.*?['\"]([a-f0-9]+)['\"]", description, re.IGNORECASE
    )
    if ocp_match:
        headers["Ocp-Apim-Subscription-Key"] = ocp_match.group(1)

    # Extract generic API keys
    api_key_match = re.search(
        r"(?:api[_-]?key|apikey).*?['\"]([a-zA-Z0-9-]+)['\"]",
        description,
        re.IGNORECASE,
    )
    if api_key_match and "Ocp-Apim-Subscription-Key" not in headers:
        headers["api-key"] = api_key_match.group(1)

    return headers


def fill_url_template(url_template: str, inputs: dict[str, Any]) -> str:
    """Replace {placeholders} in URL with actual values"""
    filled_url = url_template

    for key, value in inputs.items():
        filled_url = filled_url.replace(f"{{{key}}}", str(value))

    # Check if there are still unfilled placeholders
    remaining = re.findall(r"\{(\w+)\}", filled_url)
    if remaining:
        raise ValueError(f"Missing required inputs: {remaining}")

    return filled_url


def list_available_councils(councils_dir: Path) -> list[str]:
    """List all councils with YAML configs"""
    if not councils_dir.exists():
        return []

    return sorted([f.stem for f in councils_dir.glob("*.yaml")])
