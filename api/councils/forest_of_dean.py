"""Forest of Dean: Salesforce flow lookup for waste collections by property address."""

from __future__ import annotations

from api.councils._base import Meta
from api.councils._platforms.salesforce_flow import SalesforceFlow, SalesforceFlowConfig

SCRAPER = SalesforceFlow(
    Meta(
        title="Forest of Dean District Council",
        url="https://www.fdean.gov.uk/",
        lads=("E07000080",),
        cases={
            "Southfield Road, Coleford": {
                "house_number": "8",
                "street": "SOUTHFIELD ROAD",
                "postcode": "GL16 8BZ",
            },
            "Wynols Close, Broadwell": {
                "house_number": "36",
                "street": "WYNOLS CLOSE",
                "postcode": "GL16 7RR",
            },
        },
    ),
    SalesforceFlowConfig(host="community.fdean.gov.uk", client_code="FOD"),
)
