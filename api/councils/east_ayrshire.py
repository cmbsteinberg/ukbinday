"""East Ayrshire: ReCollect."""

from api.councils._base import Meta
from api.councils._platforms.recollect import ReCollect, ReCollectConfig

SCRAPER = ReCollect(
    Meta(
        title="East Ayrshire Council",
        url="https://www.east-ayrshire.gov.uk/",
        lads=("S12000008",),
        cases={
            "39 Heathfield Road, Auchinleck": {
                "house_number": "39",
                "street": "Heathfield Road",
                "postcode": "KA18 2JB",
            },
            "6 Sim Gardens, Darvel": {
                "house_number": "6",
                "street": "Sim Gardens",
                "postcode": "KA17 0LD",
            },
        },
    ),
    ReCollectConfig(area="EastAyrshireUK", service="waste", days=365, days_back=30),
)
