from api.councils._base import Meta
from api.councils._platforms.cloud9 import Cloud9, Cloud9Config

SCRAPER = Cloud9(
    Meta(
        title="North Herts Council",
        url="https://www.north-herts.gov.uk/",
        lads=("E07000099",),
        cases={"Example": {"postcode": "SG4 9QY", "house_number": "26", "street": "BENSLOW RISE"}, "Example fuzzy matching": {"postcode": "SG6 4EG", "house_number": "4", "street": "Wilbury Road"}},
    ),
    Cloud9Config(authority="northherts", lookup="uprn_then_address"),
)
