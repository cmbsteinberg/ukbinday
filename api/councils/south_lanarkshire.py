"""South Lanarkshire: Bartec public dashboard."""

from api.councils._base import Meta
from api.councils._platforms.bartec import Bartec, BartecConfig

_DASHBOARD_URL = "https://wasteservices.southlanarkshire.gov.uk/PublicDashboard"

SCRAPER = Bartec(
    Meta(
        title="South Lanarkshire Council",
        url=_DASHBOARD_URL,
        lads=("S12000029",),
        cases={
            "1 Clincarthill Road, Glasgow, G73 2LF": {
                "postcode": "G73 2LF",
                "uprn": "484129473",
            },
            "55 Chapel Court, Glasgow, G73 1UR": {
                "postcode": "G73 1UR",
                "uprn": "484000600",
            },
            "Flat 1 10, Burnside Lane, Hamilton, ML3 6QP": {
                "postcode": "ML3 6QP",
                "uprn": "484073020",
            },
        },
    ),
    BartecConfig(url=_DASHBOARD_URL),
)
