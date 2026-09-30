import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)


class LookupDatabaseError(Exception):
    """Raised when the postcode lookup database is not loaded."""


class PostcodeNotFoundError(Exception):
    """Raised when a postcode is not in the lookup database."""


class NoScraperError(Exception):
    """Raised when a council exists but has no scraper mapped."""


def _normalize_postcode(postcode: str) -> str:
    """Strip whitespace and uppercase — matches the parquet lookup format."""
    return re.sub(r"\s+", "", postcode).upper()


@dataclass
class LocalAuthority:
    name: str
    slug: str
    homepage_url: str
    lad_code: str = ""


class CouncilLookup:
    def __init__(self) -> None:
        self._data_dir = Path(__file__).parent.parent / "data"
        self._postcode_parquet = self._data_dir / "postcode_lookup.parquet"
        self._lad_json = self._data_dir / "lad_lookup.json"

        # Load LAD metadata
        self.lad_loaded = False
        if self._lad_json.exists():
            with open(self._lad_json) as f:
                self._lad_to_council = json.load(f)
            self.lad_loaded = True
        else:
            logger.warning("lad_lookup.json not found, local lookup will fail")
            self._lad_to_council = {}

        # Initialize duckdb for fast parquet queries
        self._con = None
        self.parquet_loaded = False
        if self._postcode_parquet.exists():
            self._con = duckdb.connect()
            self.parquet_loaded = True
        else:
            logger.warning("postcode_lookup.parquet not found, local lookup will fail")

    async def close(self) -> None:
        if self._con is not None:
            self._con.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def get_local_authority(self, postcode: str) -> list[LocalAuthority]:
        """Look up local authorities by postcode via local parquet lookup.

        Raises:
            LookupDatabaseError: if the parquet database is not loaded.
            PostcodeNotFoundError: if the postcode is not in the database.
        """
        if self._con is None:
            raise LookupDatabaseError("Postcode lookup database is not loaded")

        pc_clean = _normalize_postcode(postcode)
        logger.info("Looking up local authority locally for postcode %s", pc_clean)

        rows = self._con.execute(
            "SELECT DISTINCT lad_code FROM read_parquet(?) WHERE postcode = ?",
            [str(self._postcode_parquet), pc_clean],
        ).fetchall()

        if not rows:
            raise PostcodeNotFoundError(
                f"Postcode {pc_clean} not found in our database"
            )

        lad_codes = [r[0] for r in rows]
        authorities = []
        for lad in lad_codes:
            council = self._lad_to_council.get(lad)
            if council:
                authorities.append(
                    LocalAuthority(
                        name=council["name"],
                        slug=council["scraper_id"] or "",
                        homepage_url=council["url"] or "",
                        lad_code=lad,
                    )
                )

        if not authorities:
            logger.warning(
                "Postcode %s found but no LAD metadata matching %s",
                pc_clean,
                lad_codes,
            )

        return authorities

    async def get_authority_by_slug(self, slug: str) -> LocalAuthority:
        """Look up a specific local authority by its slug (scraper_id)."""
        logger.info("Looking up authority by slug: %s", slug)

        for lad, council in self._lad_to_council.items():
            if council["scraper_id"] == slug:
                return LocalAuthority(
                    name=council["name"],
                    slug=slug,
                    homepage_url=council["url"] or "",
                    lad_code=lad,
                )

        raise ValueError(f"Authority with slug '{slug}' not found locally")
