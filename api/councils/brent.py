from api.councils._base import Meta
from api.councils._platforms.societyworks import SocietyWorks, SocietyWorksConfig

SCRAPER = SocietyWorks(
    Meta(
        title="London Borough of Brent",
        url="https://recyclingservices.brent.gov.uk/waste",
        lads=("E09000005",),
        cases={"Brent": {"postcode": "HA3 0QU", "house_number": "25"}},
    ),
    SocietyWorksConfig(base_url="https://recyclingservices.brent.gov.uk/"),
)
