"""Staffordshire Moorlands: Bartec public dashboard."""

from api.councils._base import Meta
from api.councils._platforms.bartec import Bartec, BartecConfig

SCRAPER = Bartec(
    Meta(
        title="Staffordshire Moorlands District Council",
        url="https://www.staffsmoorlands.gov.uk",
        lads=("E07000198",),
        cases={
            "Managers Accommodation Roaring Meg": {
                "postcode": "ST8 7EA",
                "uprn": "10010602737",
            },
            "34 Pennine Way, Biddulph": {
                "postcode": "ST8 7EA",
                "uprn": "100031858191",
            },
        },
    ),
    BartecConfig(url="https://bins.staffsmoorlands.gov.uk/PublicDashboard"),
)
