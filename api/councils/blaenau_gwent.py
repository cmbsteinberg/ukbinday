from api.councils._base import Meta
from api.councils._platforms.itouchvision import ITouchVision, ITouchVisionConfig

SCRAPER = ITouchVision(
    Meta(
        title="Blaenau Gwent County Borough Council",
        url="https://www.blaenau-gwent.gov.uk/",
        lads=("W06000019",),
        cases={
        "test": {"uprn": "100100457787"},
        },
    ),
    ITouchVisionConfig(client_id=106, council_id=35,),
)
