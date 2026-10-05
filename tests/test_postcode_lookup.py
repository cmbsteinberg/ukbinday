"""Postcode → LAD from the committed outward-code shards (api/data/postcodes/)."""

from __future__ import annotations

import pytest

from api.services.council_lookup import CouncilLookup, PostcodeNotFoundError
from scripts.lookup.create_lookup_table import (
    ONSPD_SOURCE,
    POSTCODES_DIR,
    build_shards,
    stale_shards,
)

pytestmark = pytest.mark.ci


@pytest.fixture(scope="module")
def lookup() -> CouncilLookup:
    return CouncilLookup()


def test_shards_are_up_to_date() -> None:
    """The committed shards are exactly what the committed parquet builds."""
    shards = build_shards(ONSPD_SOURCE)
    assert stale_shards(shards, POSTCODES_DIR) == []


@pytest.mark.asyncio(loop_scope="session")
async def test_normalises_input(lookup: CouncilLookup) -> None:
    (la,) = await lookup.get_local_authority(" sw1a 1aa ")
    assert la.lad_code == "E09000033"


@pytest.mark.asyncio(loop_scope="session")
async def test_outward_code_split_between_councils(lookup: CouncilLookup) -> None:
    (la,) = await lookup.get_local_authority("SW1A 0WY")
    assert la.lad_code == "E09000032"  # Wandsworth, beside Westminster's SW1A 1AA


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("postcode", ["SW1A 9XX", "ZZ99 9ZZ", "../etc/x", "", "AB"])
async def test_unknown_postcode(lookup: CouncilLookup, postcode: str) -> None:
    with pytest.raises(PostcodeNotFoundError):
        await lookup.get_local_authority(postcode)
