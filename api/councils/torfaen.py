from api.councils._base import Meta
from api.councils._platforms.itouchvision import ITouchVision, ITouchVisionConfig

SCRAPER = ITouchVision(
    Meta(
        title="Torfaen County Borough Council",
        url="https://www.torfaen.gov.uk/",
        lads=("W06000020",),
        cases={
        "NP4 6LU": {"uprn": "100100800320"},
        "NP44 3DN": {"uprn": "100100789478"},
        "NP4 8HQ": {"uprn": "100100798047"},
        },
    ),
    ITouchVisionConfig(client_id=80, council_id=397,),
)
