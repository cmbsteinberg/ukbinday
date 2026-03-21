import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

ADDRESS_API_URL = "https://www.midsuffolk.gov.uk/api/jsonws/invoke"
LOCAL_AUTHORITY_API = "https://www.gov.uk/api/local-authority"

ADDRESS_HEADERS = {
    "accept": "*/*",
    "content-type": "text/plain;charset=UTF-8",
    "x-csrf-token": "Ba9vI91W",
}

ADDRESS_BODY_TEMPLATE = (
    '{"/placecube_digitalplace.addresscontext/search-address-by-postcode":'
    '{"companyId":"1486681","postcode":"%s","fallbackToNationalLookup":false}}'
)


@dataclass
class Address:
    uprn: str
    full_address: str
    postcode: str


@dataclass
class LocalAuthority:
    name: str
    slug: str
    tier: str
    homepage_url: str
    parent_name: str | None = None
    parent_slug: str | None = None


class AddressLookup:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=15, follow_redirects=True)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def search_addresses(self, postcode: str) -> list[Address]:
        postcode = postcode.strip().upper()
        logger.info("Searching addresses for postcode %s", postcode)

        body = ADDRESS_BODY_TEMPLATE % postcode
        resp = await self._client.post(
            ADDRESS_API_URL, headers=ADDRESS_HEADERS, content=body
        )
        resp.raise_for_status()
        data = resp.json()

        addresses = [
            Address(
                uprn=item["UPRN"],
                full_address=item["fullAddress"],
                postcode=item["postcode"],
            )
            for item in data
        ]
        logger.info("Found %d addresses for %s", len(addresses), postcode)
        return addresses

    async def get_local_authority(self, postcode: str) -> LocalAuthority | list[dict]:
        """Look up local authority by postcode via gov.uk API.

        Returns a LocalAuthority if the postcode maps to a single authority,
        or a list of address dicts if the postcode spans multiple authorities.
        """
        postcode_clean = postcode.strip()
        logger.info("Looking up local authority for postcode %s", postcode_clean)

        resp = await self._client.get(
            LOCAL_AUTHORITY_API, params={"postcode": postcode_clean}
        )
        resp.raise_for_status()
        data = resp.json()

        # If redirected to a single authority (301 -> 200 after follow)
        if "local_authority" in data:
            return self._parse_authority(data["local_authority"])

        # Multiple authorities — return address list for user to pick
        if "addresses" in data:
            logger.info(
                "Postcode %s spans %d authorities",
                postcode_clean,
                len(data["addresses"]),
            )
            return data["addresses"]

        logger.warning("Unexpected response for postcode %s: %s", postcode_clean, data)
        return []

    async def get_authority_by_slug(self, slug: str) -> LocalAuthority:
        """Look up a specific local authority by its slug."""
        logger.info("Looking up authority by slug: %s", slug)
        resp = await self._client.get(f"{LOCAL_AUTHORITY_API}/{slug}")
        resp.raise_for_status()
        return self._parse_authority(resp.json()["local_authority"])

    def _parse_authority(self, data: dict) -> LocalAuthority:
        parent = data.get("parent")
        authority = LocalAuthority(
            name=data["name"],
            slug=data["slug"],
            tier=data["tier"],
            homepage_url=data["homepage_url"],
            parent_name=parent["name"] if parent else None,
            parent_slug=parent["slug"] if parent else None,
        )
        logger.info(
            "Resolved authority: %s (slug=%s, tier=%s)",
            authority.name,
            authority.slug,
            authority.tier,
        )
        return authority
