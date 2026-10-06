"""Dover: resolve a UPRN through the waste portal, then fetch its collection schedule."""

from __future__ import annotations

from api.councils._base import Meta
from api.councils._platforms.waste_portal import WastePortal, WastePortalConfig

SCRAPER = WastePortal(
    Meta(
        title="Dover District Council",
        url="https://www.dover.gov.uk",
        lads=("E07000108",),
        cases={
            "200002423404": {"uprn": "200002423404"},
            "100060905828": {"uprn": "100060905828"},
        },
    ),
    WastePortalConfig(api_url="https://portal.waste.dover.gov.uk/api", council_id="39"),
)
