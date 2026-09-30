from api.councils._base import Meta
from api.councils._platforms.itouchvision import ITouchVision, ITouchVisionConfig

SCRAPER = ITouchVision(
    Meta(
        title="Winchester City Council",
        url="https://www.winchester.gov.uk",
        lads=("E07000094",),
        cases={
        "test": {"uprn": "10090844134"},
        },
    ),
    ITouchVisionConfig(client_id=43, council_id=433,),
)
