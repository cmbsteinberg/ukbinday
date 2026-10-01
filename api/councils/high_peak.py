"""High Peak: Bartec public dashboard."""

from api.councils._base import Meta
from api.councils._platforms.bartec import Bartec, BartecConfig

SCRAPER = Bartec(
    Meta(
        title="High Peak Borough Council",
        url="https://www.highpeak.gov.uk/",
        lads=("E07000037",),
        cases={
            "SK23 6BQ 10010724045": {"postcode": "SK23 6BQ", "uprn": "10010724045"},
            "S33 7ZA, 10010747174": {"postcode": "S33 7ZA", "uprn": "10010747174"},
            "SK13 2AD, 10010734345": {"postcode": "SK13 2AD", "uprn": "10010734345"},
        },
    ),
    BartecConfig(url="https://bins.highpeak.gov.uk/PublicDashboard"),
)
