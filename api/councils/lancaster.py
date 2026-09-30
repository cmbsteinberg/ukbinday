from api.councils._base import Meta
from api.councils._platforms.whitespace import Whitespace, WhitespaceConfig

SCRAPER = Whitespace(
    Meta(
        title="Lancaster City Council",
        url="https://www.lancaster.gov.uk",
        lads=("E07000121",),
        cases={"1 Queen Street": {"postcode": "LA1 1RS", "house_number": "1", "street": "Queen Street"}},
    ),
    WhitespaceConfig(
        base_url="https://lcc-wrp.whitespacews.com",
        strip_suffixes=(" Collection Service", " Collection - refer to calendar for stream"),
    ),
)
