"""Mid Suffolk: submit a UPRN to the Placecube/Liferay collection-day portlet."""

from __future__ import annotations

from api.councils._base import Meta
from api.councils._platforms.placecube import Placecube, PlacecubeConfig

SCRAPER = Placecube(
    Meta(
        title="Mid Suffolk District Council",
        url="https://www.midsuffolk.gov.uk/check-your-collection-day",
        lads=("E07000203",),
        cases={"Test_001": {"uprn": "100091488908"}},
    ),
    PlacecubeConfig(base_url="https://www.midsuffolk.gov.uk"),
)
