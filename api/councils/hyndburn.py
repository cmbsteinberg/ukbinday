from api.councils._base import Meta
from api.councils._platforms.itouchvision import ITouchVision, ITouchVisionConfig

SCRAPER = ITouchVision(
    Meta(
        title="Hyndburn Borough Council",
        url="https://www.hyndburnbc.gov.uk/",
        lads=("E07000120",),
        cases={
        "test": {"uprn": "100010439798"},
        },
    ),
    ITouchVisionConfig(client_id=157, council_id=34508,
        api_url="https://itouchvision.app/portal/itouchvision/kmbd/collectionDay",),
)
