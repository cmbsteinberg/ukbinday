from api.councils._base import Meta
from api.councils._platforms.cloud9 import Cloud9, Cloud9Config

SCRAPER = Cloud9(
    Meta(
        title="Southend-on-Sea City Council",
        url="https://www.southend.gov.uk",
        lads=("E06000033",),
        cases={"Test_001": {"uprn": "100090691871"}, "Test_002": {"postcode": "SS3 9JD", "house_number": "38", "street": "Thorpedene Gardens"}},
    ),
    Cloud9Config(authority="southend", lookup="uprn_or_address"),
)
