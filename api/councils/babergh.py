"""Babergh District Council: posts a UPRN to its Placecube/Liferay collection-day form."""

from __future__ import annotations

from api.councils._base import Meta
from api.councils._platforms.placecube import Placecube, PlacecubeConfig

SCRAPER = Placecube(
    Meta(
        title="Babergh District Council",
        url="https://babergh.gov.uk/check-your-collection-day",
        lads=("E07000200",),
        cases={"Test_001": {"uprn": "100091085564"}},
    ),
    PlacecubeConfig(base_url="https://babergh.gov.uk"),
)
