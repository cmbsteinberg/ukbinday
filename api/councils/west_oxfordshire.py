"""West Oxfordshire: Salesforce flow lookup for a property's waste collections."""

from __future__ import annotations

from api.councils._base import Meta
from api.councils._platforms.salesforce_flow import SalesforceFlow, SalesforceFlowConfig

SCRAPER = SalesforceFlow(
    Meta(
        title="West Oxfordshire District Council",
        url="https://westoxon.gov.uk/",
        lads=("E07000181",),
        cases={
            "75 manor road woodstock": {
                "address": "75 manor road woodstock, ox20 1xr",
                "house_number": "75",
                "street": "Manor Road",
                "postcode": "OX20 1XR",
            },
            "65 main road long hanborough": {
                "address": "65 MAIN ROAD, LONG HANBOROUGH, WITNEY, OX29 8JX",
                "house_number": "65",
                "street": "Main Road",
                "postcode": "OX29 8JX",
            },
        },
    ),
    SalesforceFlowConfig(
        host="community.westoxon.gov.uk",
        client_code="WOD",
        label_only=True,
        loaded={
            "APPLICATION@markup://siteforce:communityApp": "vgD8vvaBHzgKYqb_JQjQdw",
            "COMPONENT@markup://flowruntime:flowRuntimeForFlexiPage": "6vLCX6RcjM4U8N2_kygrQw",
            "COMPONENT@markup://instrumentation:o11ySecondaryLoader": "1JitVv-ZC5qlK6HkuofJqQ",
        },
    ),
)
