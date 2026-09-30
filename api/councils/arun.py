from api.councils._base import Meta
from api.councils._platforms.cloud9 import Cloud9, Cloud9Config

SCRAPER = Cloud9(
    Meta(
        title="Arun District Council",
        url="https://www.arun.gov.uk",
        lads=("E07000224",),
        cases={"Test_001": {"postcode": "BN17 5JA", "house_number": "21A", "street": "Beach Road"}, "Test_002": {"uprn": "100062180214"}},
    ),
    Cloud9Config(authority="arun", lookup="uprn_or_address"),
)
