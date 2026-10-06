"""Lewes: EnvironmentFirst bin lookup by UPRN, with a legacy URL fallback."""

from __future__ import annotations

from api.councils._base import Meta
from api.councils._platforms.environment_first import (
    EnvironmentFirst,
    EnvironmentFirstConfig,
)

SCRAPER = EnvironmentFirst(
    Meta(
        title="Lewes",
        url="https://www.lewes-eastbourne.gov.uk/article/1158/When-is-my-bin-collection-day",
        lads=("E07000063",),
        cases={},
    ),
    EnvironmentFirstConfig(),
)
