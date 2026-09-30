from api.councils._base import Meta
from api.councils._platforms.itouchvision import ITouchVision, ITouchVisionConfig

SCRAPER = ITouchVision(
    Meta(
        title="Test Valley Borough Council",
        url="https://www.testvalley.gov.uk/",
        lads=("E07000093",),
        cases={
        "test": {"uprn": "100060571645"},
        },
    ),
    ITouchVisionConfig(client_id=94, council_id=390,),
)
