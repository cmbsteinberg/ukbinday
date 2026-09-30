from api.councils._base import Meta
from api.councils._platforms.whitespace import Whitespace, WhitespaceConfig

SCRAPER = Whitespace(
    Meta(
        title="Surrey Heath",
        url="https://asjwsw-wrpsurreyheathmunicipal-live.whitespacews.com/",
        lads=("E07000214",),
        cases={"Surrey Heath": {"house_number": "36", "postcode": "GU20 6PN"}},
    ),
    WhitespaceConfig(
        base_url="https://asjwsw-wrpsurreyheathmunicipal-live.whitespacews.com",
        match="first",
        rename={"Batteries-small electricals-textiles": "Batteries/small electricals/textiles"},
    ),
)
