from api.councils._base import Meta, Transport
from api.councils._platforms.societyworks import SocietyWorks, SocietyWorksConfig

SCRAPER = SocietyWorks(
    Meta(
        title="Kingston upon Thames Council",
        url="https://www.kingston.gov.uk",
        lads=("E09000021",),
        cases={
            "Test_001": {
                "postcode": "KT3 3EG",
                "house_number": "25",
                "street": "Beechcroft Avenue",
            }
        },
    ),
    SocietyWorksConfig(
        base_url="https://waste-services.kingston.gov.uk/",
        transport=Transport.CURL_CFFI,
        strip_suffix=" collection",
    ),
)
