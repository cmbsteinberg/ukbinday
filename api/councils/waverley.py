from api.councils._base import Meta
from api.councils._platforms.whitespace import Whitespace, WhitespaceConfig

SCRAPER = Whitespace(
    Meta(
        title="Waverley Borough Council",
        url="https://waverley.gov.uk",
        lads=("E07000216",),
        cases={
            "Example": {"postcode": "GU8 5QQ", "house_number": "1", "street": "Gasden Drive"},
            "Example No Postcode Space": {"postcode": "GU85QQ", "house_number": "1", "street": "Gasden Drive"},
        },
    ),
    WhitespaceConfig(base_url="https://wav-wrp.whitespacews.com", strip_suffixes=(" Collection Service",)),
)
