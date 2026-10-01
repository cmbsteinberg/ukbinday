"""Stirling: ReCollect."""

from api.councils._base import Meta
from api.councils._platforms.recollect import ReCollect, ReCollectConfig

SCRAPER = ReCollect(
    Meta(
        title="Stirling Council",
        url="https://www.stirling.gov.uk",
        lads=("S12000030",),
        cases={
            "Test_001": {
                "postcode": "FK9 4QA",
                "house_number": "5",
                "street": "Sunnylaw Road",
            },
        },
    ),
    ReCollectConfig(area="StirlingUK", service="waste", days=90),
)
