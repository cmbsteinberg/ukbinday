from api.councils._base import Meta
from api.councils._platforms.itouchvision import ITouchVision, ITouchVisionConfig

SCRAPER = ITouchVision(
    Meta(
        title="Epsom and Ewell Borough Council",
        url="https://www.epsom-ewell.gov.uk/",
        lads=("E07000208",),
        cases={
        "test": {"uprn": "100061349867"},
        },
    ),
    ITouchVisionConfig(client_id=138, council_id=140,),
)
