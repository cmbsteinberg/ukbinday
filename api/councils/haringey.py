"""Haringey: resolve a UPRN to a point ID, then fetch that point's collection schedule."""

from __future__ import annotations

from api.councils._base import Meta
from api.councils._platforms.waste_portal import WastePortal, WastePortalConfig

SCRAPER = WastePortal(
    Meta(
        title="Haringey Council",
        url="https://www.haringey.gov.uk/",
        lads=("E09000014",),
        cases={
            "Test_001": {"uprn": "100021209182"},
            "Test_002": {"uprn": "100021207181"},
            "Test_003": {"uprn": "100021202738"},
        },
    ),
    WastePortalConfig(api_url="https://wastecollections.haringey.gov.uk/api", council_id="45"),
)
