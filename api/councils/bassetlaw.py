"""Bassetlaw: ReCollect."""

from api.councils._base import Meta
from api.councils._platforms.recollect import ReCollect, ReCollectConfig

SCRAPER = ReCollect(
    Meta(
        title="Bassetlaw District Council",
        url="https://www.bassetlaw.gov.uk/waste-and-recycling/bin-collections/",
        lads=("E07000171",),
        cases={
            "Albert Road, Retford": {
                "postcode": "DN22 6JB",
                "house_number": "10",
                "street": "Albert Road",
            },
            "Albert Street, Worksop": {
                "postcode": "S80 1QR",
                "house_number": "10",
                "street": "Albert Street",
            },
        },
    ),
    ReCollectConfig(area="BassetlawUK", service="50015", days=120),
)
