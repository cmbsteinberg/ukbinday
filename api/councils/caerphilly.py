"""Caerphilly: ReCollect."""

from api.councils._base import Meta
from api.councils._platforms.recollect import ReCollect, ReCollectConfig

SCRAPER = ReCollect(
    Meta(
        title="Caerphilly County Borough",
        url="https://www.caerphilly.gov.uk",
        lads=("W06000018",),
        cases={},
    ),
    ReCollectConfig(area="CaerphillyCountyUK", service="50008", days=60),
)
