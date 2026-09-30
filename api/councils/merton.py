from api.councils._base import Meta
from api.councils._platforms.societyworks import SocietyWorks, SocietyWorksConfig

SCRAPER = SocietyWorks(
    Meta(
        title="London Borough of Merton",
        url="https://fixmystreet.merton.gov.uk/waste/",
        lads=("E09000024",),
        cases={"Merton": {"postcode": "SW19 1QT", "house_number": "16", "uprn": "4328213"}},
    ),
    SocietyWorksConfig(base_url="https://fixmystreet.merton.gov.uk/"),
)
