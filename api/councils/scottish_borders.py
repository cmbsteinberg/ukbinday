"""Scottish Borders: Bartec public dashboard (the embeddable collection calendar)."""

from api.councils._base import Meta
from api.councils._platforms.bartec import Bartec, BartecConfig

URL = "https://scotborders-live-portal.bartecmunicipal.com/Embeddable/CollectionCalendar"

SCRAPER = Bartec(
    Meta(
        title="Scottish Borders Council",
        url=URL,
        lads=("S12000026",),
        cases={"Test": {"uprn": "116073632", "postcode": "TD9 9HL"}},
    ),
    BartecConfig(url=URL),
)
