from api.councils._base import Meta
from api.councils._platforms.whitespace import Whitespace, WhitespaceConfig

SCRAPER = Whitespace(
    Meta(
        title="Woking",
        url="https://asjwsw-wrpwokingmunicipal-live.whitespacews.com/",
        lads=("E07000217",),
        cases={"Woking": {"house_number": "2", "postcode": "GU21 4JY"}},
    ),
    WhitespaceConfig(
        base_url="https://asjwsw-wrpwokingmunicipal-live.whitespacews.com",
        match="first",
        rename={"Batteries-small electricals-textiles": "Batteries/small electricals/textiles"},
    ),
)
