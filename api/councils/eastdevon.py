from api.councils._base import Meta
from api.councils._platforms.cloud9 import Cloud9, Cloud9Config

SCRAPER = Cloud9(
    Meta(
        title="East Devon District Council",
        url="https://eastdevon.gov.uk/",
        lads=("E07000040",),
        cases={"Test_001": {"uprn": "10000246114"}, "Test_002": {"uprn": "10000272679"}},
    ),
    Cloud9Config(authority="eastdevon", lookup="uprn", uprn_width=12),
)
