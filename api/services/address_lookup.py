import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
import ibis

logger = logging.getLogger(__name__)

ADDRESS_API_URL = "https://www.midsuffolk.gov.uk/api/jsonws/invoke"

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
        self._data_dir = Path(__file__).parent.parent / "data"
        self._postcode_parquet = self._data_dir / "postcode_lookup.parquet"
        self._lad_json = self._data_dir / "lad_lookup.json"

        # Load LAD metadata
        if self._lad_json.exists():
            with open(self._lad_json) as f:
                self._lad_to_council = json.load(f)
        else:
            logger.warning("lad_lookup.json not found, local lookup will fail")
            self._lad_to_council = {}

        # Initialize ibis/duckdb for fast parquet queries
        if self._postcode_parquet.exists():
            self._con = ibis.duckdb.connect()
            self._postcodes = self._con.read_parquet(self._postcode_parquet)
        else:
            logger.warning("postcode_lookup.parquet not found, local lookup will fail")
            self._postcodes = None

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
        """Look up local authority by postcode via local parquet lookup.

        Returns a LocalAuthority if the postcode maps to a single authority,
        or a list of council info dicts if the postcode spans multiple authorities.
        """
        if self._postcodes is None:
            logger.error("Local lookup database not initialized")
            return []

        pc_clean = re.sub(r"\s+", "", postcode).upper()
        logger.info("Looking up local authority locally for postcode %s", pc_clean)

        # Query parquet for LAD codes
        res = self._postcodes.filter(self._postcodes.postcode == pc_clean).execute()

        if res.empty:
            logger.warning("Postcode %s not found in local lookup", pc_clean)
            return []

        lad_codes = res["lad_code"].unique()
        authorities = []
        for lad in lad_codes:
            council = self._lad_to_council.get(lad)
            if council:
                authorities.append(
                    LocalAuthority(
                        name=council["name"],
                        slug=council["scraper_id"] or "",
                        tier="unitary",
                        homepage_url=council["url"] or "",
                    )
                )

        if len(authorities) == 1:
            return authorities[0]
        elif len(authorities) > 1:
            logger.info(
                "Postcode %s spans %d authorities locally",
                pc_clean,
                len(authorities),
            )
            return [
                {"name": a.name, "homepage_url": a.homepage_url} for a in authorities
            ]

        logger.warning("Postcode %s found but no LAD metadata matching %s", pc_clean, lad_codes)
        return []

    async def get_authority_by_slug(self, slug: str) -> LocalAuthority:
        """Look up a specific local authority by its slug (scraper_id)."""
        logger.info("Looking up authority by slug: %s", slug)

        for lad, council in self._lad_to_council.items():
            if council["scraper_id"] == slug:
                return LocalAuthority(
                    name=council["name"],
                    slug=slug,
                    tier="unitary",
                    homepage_url=council["url"] or ""
                )

        raise ValueError(f"Authority with slug '{slug}' not found locally")
