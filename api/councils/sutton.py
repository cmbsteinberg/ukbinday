from api.councils._base import Meta
from api.councils._platforms.societyworks import SocietyWorks, SocietyWorksConfig

SCRAPER = SocietyWorks(
    Meta(
        title="London Borough of Sutton",
        url="https://waste-services.sutton.gov.uk/waste",
        lads=("E09000029",),
        cases={"Sutton": {"postcode": "SM1 4BJ", "house_number": "54", "uprn": "4473006"}},
    ),
    SocietyWorksConfig(base_url="https://waste-services.sutton.gov.uk/"),
)
