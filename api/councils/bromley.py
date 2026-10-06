from api.councils._base import Meta
from api.councils._platforms.societyworks import SocietyWorks, SocietyWorksConfig

SCRAPER = SocietyWorks(
    Meta(
        title="Bromley Borough Council",
        url="https://recyclingservices.bromley.gov.uk",
        lads=("E09000006",),
        cases={
            "Test_001": {
                "postcode": "BR1 3PU",
                "house_number": "17",
                "street": "College Road",
            },
        },
    ),
    SocietyWorksConfig(base_url="https://recyclingservices.bromley.gov.uk/", strip_suffix=" collection"),
)
