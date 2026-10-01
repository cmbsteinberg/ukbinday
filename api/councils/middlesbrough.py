"""Middlesbrough: ReCollect."""

from api.councils._base import Meta
from api.councils._platforms.recollect import ReCollect, ReCollectConfig

SCRAPER = ReCollect(
    Meta(
        title="Middlesbrough",
        url="https://www.middlesbrough.gov.uk/recycling-and-rubbish/bin-collection-dates/",
        lads=("E06000002",),
        cases={},
    ),
    ReCollectConfig(area="MiddlesbroughUK", service="50005", days=60),
)
