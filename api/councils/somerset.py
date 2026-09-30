from api.councils._base import Meta
from api.councils._platforms.itouchvision import ITouchVision, ITouchVisionConfig

SCRAPER = ITouchVision(
    Meta(
        title="Somerset Council",
        url="https://www.somerset.gov.uk/",
        lads=("E06000066",),
        cases={
        "test": {"uprn": "30071272"},
        },
    ),
    ITouchVisionConfig(client_id=129, council_id=34493,),
)
