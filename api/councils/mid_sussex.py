from api.councils._base import Meta
from api.councils._platforms.whitespace import Whitespace, WhitespaceConfig

SCRAPER = Whitespace(
    Meta(
        title="Mid Sussex District Council (Whitespace WRP)",
        url="https://www.midsussex.gov.uk/waste-and-recycling/",
        lads=("E07000228",),
        cases={
            "23 High Street": {"house_number": "23", "street": "HIGH STREET", "postcode": "RH17 6TB"},
            "Hapstead Hall": {"house_number": "HAPSTEAD HALL", "street": "HIGH STREET", "postcode": "RH17 6TB"},
            "The Gardeners Arms": {
                "house_number": "THE GARDENERS ARMS",
                "street": "SELSFIELD ROAD",
                "postcode": "RH17 6TJ",
            },
        },
    ),
    WhitespaceConfig(base_url="https://sms-wrp.whitespacews.com", upper=True),
)
