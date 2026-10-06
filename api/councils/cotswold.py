"""Cotswold: Salesforce flow lookup using the full address label."""

from __future__ import annotations

from api.councils._base import Meta
from api.councils._platforms.salesforce_flow import SalesforceFlow, SalesforceFlowConfig

SCRAPER = SalesforceFlow(
    Meta(
        title="Cotswold District Council",
        url="https://www.cotswold.gov.uk/",
        lads=("E07000079",),
        cases={
            "Parsons Piece, 1 Glebe Lane, Kemble, Cirencester": {
                "address": "PARSONS PIECE, 1 GLEBE LANE, KEMBLE, CIRENCESTER, GL7 6BD"
            },
        },
    ),
    SalesforceFlowConfig(
        host="community.cotswold.gov.uk", client_code="CDC", label_only=True, exact_label=True
    ),
)
