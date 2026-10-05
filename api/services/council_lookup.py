import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


class LookupDatabaseError(Exception):
    """Raised when the postcode lookup database is not loaded."""


class PostcodeNotFoundError(Exception):
    """Raised when a postcode is not in the lookup database."""


class NoScraperError(Exception):
    """Raised when a council exists but has no scraper mapped."""


def _normalize_postcode(postcode: str) -> str:
    """Strip whitespace and uppercase — matches the shard keys."""
    return re.sub(r"\s+", "", postcode).upper()


@dataclass
class LocalAuthority:
    """A council a postcode resolves to. Whether it's wired is the registry's call."""

    name: str
    homepage_url: str
    lad_code: str


class CouncilLookup:
    def __init__(self) -> None:
        self._data_dir = Path(__file__).parent.parent / "data"
        self._postcodes_dir = self._data_dir / "postcodes"
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

        # One JSON file per outward code, from scripts/lookup/create_lookup_table.py
        self.postcodes_loaded = self._postcodes_dir.is_dir()
        if not self.postcodes_loaded:
            logger.warning("api/data/postcodes/ not found, local lookup will fail")

    @lru_cache(maxsize=512)  # noqa: B019 -- one instance per app, shards never change
    def _shard(self, outward: str) -> dict | None:
        path = self._postcodes_dir / f"{outward}.json"
        # Outward codes are alphanumeric; anything else can't name a shard file.
        if not outward.isalnum() or not path.is_file():
            return None
        return json.loads(path.read_text())

    def _lad_code(self, postcode: str) -> str | None:
        shard = self._shard(postcode[:-3])
        if shard is None:
            return None
        index = shard["pc"].get(postcode[-3:])
        return None if index is None else shard["lads"][index]

    async def get_local_authority(self, postcode: str) -> list[LocalAuthority]:
        """Look up local authorities by postcode via the outward-code shards.

        Raises:
            LookupDatabaseError: if the shards are not present.
            PostcodeNotFoundError: if the postcode is not in the database.
        """
        if not self.postcodes_loaded:
            raise LookupDatabaseError("Postcode lookup database is not loaded")

        pc_clean = _normalize_postcode(postcode)
        logger.info("Looking up local authority locally for postcode %s", pc_clean)

        lad = self._lad_code(pc_clean)
        if lad is None:
            raise PostcodeNotFoundError(
                f"Postcode {pc_clean} not found in our database"
            )

        authorities = []
        council = self._lad_to_council.get(lad)
        if council:
            authorities.append(
                LocalAuthority(
                    name=council["name"],
                    homepage_url=council["url"] or "",
                    lad_code=lad,
                )
            )

        if not authorities:
            logger.warning(
                "Postcode %s found but no LAD metadata matching %s",
                pc_clean,
                lad,
            )

        return authorities
