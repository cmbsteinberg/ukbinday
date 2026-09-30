from api.councils._base import Meta
from api.councils._platforms.cloud9 import Cloud9, Cloud9Config

SCRAPER = Cloud9(
    Meta(
        title="Rugby Borough Council",
        url="https://www.rugby.gov.uk/",
        lads=("E07000220",),
        cases={"Test_001": {"uprn": "100070200377"}, "Test_002": {"uprn": "100070200372"}, "Test_003": {"uprn": "10010521297"}},
    ),
    Cloud9Config(authority="rugby", lookup="uprn"),
)
