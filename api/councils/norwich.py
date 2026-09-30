from api.councils._base import Meta
from api.councils._platforms.whitespace import Whitespace, WhitespaceConfig

SCRAPER = Whitespace(
    Meta(
        title="Norwich City Council",
        url="https://www.norwich.gov.uk/bins-and-recycling",
        lads=("E07000148",),
        cases={
            "GoodExample": {"house_number": "33", "street": "Carrow Road", "postcode": "NR1 1HS"},
            "FlatAddress": {"house_number": "Flat 1", "street": "Unthank Road", "postcode": "NR2 2RN"},
            "PostcodeMissingSpace": {"house_number": "258", "street": "North Park Avenue", "postcode": "NR47ED"},
        },
    ),
    WhitespaceConfig(
        base_url="https://bnr-wrp.whitespacews.com",
        strip_suffixes=(" Collection Service",),
        rename={
            "Domestic Waste": "Domestic Waste",
            "Food Waste": "Food Waste",
            "Recycling": "Recycling",
            "Garden Waste": "Garden Waste",
        },
        only_renamed=True,
    ),
)
