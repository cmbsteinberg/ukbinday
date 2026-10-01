"""Redcar and Cleveland: ReCollect."""

from api.councils._base import Meta
from api.councils._platforms.recollect import ReCollect, ReCollectConfig

SCRAPER = ReCollect(
    Meta(
        title="Redcar and Cleveland",
        url="https://www.redcar-cleveland.gov.uk",
        lads=("E06000003",),
        cases={},
    ),
    ReCollectConfig(area="RedcarandClevelandUK", service="50006", days=30),
)
