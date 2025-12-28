import httpx
import logging
from typing import Optional, List, Dict, Any
import json
import re
import time
from tenacity import retry, stop_after_attempt, wait_exponential

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# UK Postcode validation regex
POSTCODE_REGEX = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}$", re.IGNORECASE)


class PostcodeFinder:
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.client = httpx.Client(follow_redirects=True, timeout=self.timeout)
        self._last_request_time = 0
        self._min_request_interval = 1.0  # 1 request per second

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

    def close(self):
        """Explicitly close the HTTP client."""
        self.client.close()

    def _validate_postcode(self, postcode: str) -> bool:
        """Validates UK postcode format."""
        return bool(POSTCODE_REGEX.match(postcode.strip()))

    def _rate_limit(self):
        """Ensures minimum interval between requests (1 per second)."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _normalize_address(self, address: str) -> str:
        """Simplifies address string for better matching."""
        return "".join(e for e in address if e.isalnum()).lower()

    def _parse_admin_response(self, la_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts child and parent information into a flat structure."""
        parent = la_data.get("parent")
        return {
            "child_name": la_data.get("name"),
            "child_url": la_data.get("homepage_url"),
            "child_tier": la_data.get("tier"),
            "parent_name": parent.get("name") if parent else None,
            "parent_url": parent.get("homepage_url") if parent else None,
            "parent_tier": parent.get("tier") if parent else None,
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def uprn_lookup(self, postcode: str) -> List[Dict[str, str]]:
        """Fetches UPRN data for a given postcode."""
        if not self._validate_postcode(postcode):
            logger.error(f"Invalid postcode format: {postcode}")
            return []

        url = f"https://forms.north-norfolk.gov.uk/xforms/AddressSearch/GetAddressList?postcode={postcode}"
        try:
            logger.info(f"Fetching UPRN data for postcode: {postcode}")
            self._rate_limit()
            response = self.client.get(url)
            response.raise_for_status()

            items = response.json()
            return [
                {"full_address": item["text"], "uprn": item["value"]}
                for item in items
                if item.get("value") and item["value"] != "0"
            ]
        except Exception as e:
            logger.error(f"UPRN lookup failed for {postcode}: {e}")
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def admin_lookup(
        self,
        postcode: str,
        user_address: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Finds local authority details. Uses user_address to disambiguate
        if the postcode covers multiple authorities.
        """
        if not self._validate_postcode(postcode):
            logger.error(f"Invalid postcode format: {postcode}")
            return None

        api_url = f"https://www.gov.uk/api/local-authority?postcode={postcode}"

        try:
            logger.info(f"Looking up local authority for: {postcode}")
            self._rate_limit()
            response = self.client.get(api_url)
            response.raise_for_status()
            data = response.json()

            # Case 1: Direct Match (Single Authority)
            if "local_authority" in data:
                return self._parse_admin_response(data["local_authority"])

            # Case 2: Multi-match (Requires address disambiguation)
            if "addresses" in data:
                if not user_address:
                    logger.warning(
                        f"Multiple authorities for {postcode}, but no address provided."
                    )
                    return None

                norm_target = self._normalize_address(user_address)
                match = next(
                    (
                        a
                        for a in data["addresses"]
                        if self._normalize_address(a["address"]) == norm_target
                    ),
                    None,
                )

                if match:
                    logger.info(f"Matched address to slug: {match['slug']}")
                    slug_url = f"https://www.gov.uk/api/local-authority/{match['slug']}"
                    self._rate_limit()
                    slug_res = self.client.get(slug_url)
                    slug_res.raise_for_status()
                    return self._parse_admin_response(
                        slug_res.json().get("local_authority", {})
                    )

                logger.warning(
                    f"Could not find exact address match for: {user_address}"
                )
                return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.error(f"Postcode {postcode} not found in GOV.UK records.")
            else:
                logger.error(f"HTTP error occurred: {e}")
        except Exception as e:
            logger.exception(f"An unexpected error occurred: {e}")

        return None


# --- Example Usage ---
if __name__ == "__main__":
    with PostcodeFinder() as finder:
        # 1. Get addresses/UPRNs first
        addresses = finder.uprn_lookup("BR8 7RE")

        if addresses:
            # 2. Pick the first address found to find the authority
            target = addresses[0]["full_address"]
            details = finder.admin_lookup("BR8 7RE", user_address=target)

            print("\n--- Results ---")
            print(f"Address: {target}")
            print(json.dumps(details, indent=2))
