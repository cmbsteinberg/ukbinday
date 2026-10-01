"""Newcastle City Council: ReCollect."""

from api.councils._base import Meta
from api.councils._platforms.recollect import ReCollect, ReCollectConfig

SCRAPER = ReCollect(
    Meta(
        title="Newcastle City Council",
        url="https://new.newcastle.gov.uk/recycling-waste/check-your-bin-collection-day",
        lads=("E08000021",),
        cases={
            "Grange Road": {
                "house_number": "1",
                "street": "Grange Road",
                "postcode": "NE3 5LA",
            },
            "Westerhope": {
                "house_number": "1",
                "street": "Westerhope Homes Hillhead Road",
                "postcode": "NE5 1NJ",
            },
        },
    ),
    ReCollectConfig(area="NewcastleUponTyneUK", service="waste", days=120),
)
