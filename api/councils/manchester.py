"""Manchester: authenticate with the citizen API, then request bin dates by UPRN."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = (
    "https://manchester.form.uk.empro.verintcloudservices.com/api/custom"
    "?action=bin_checker-get_bin_col_info&actionedby=_KDF_custom&loadform=true"
    "&access=citizen&locale=en"
)
_AUTH_URL = (
    "https://manchester.form.uk.empro.verintcloudservices.com/api/citizen"
    "?archived=Y&preview=false&locale=en"
)
_COLLECTION_MAP = {
    "ahtm_dates_black_bin": "Black bin",
    "ahtm_dates_brown_commingled_bin": "Brown bin",
    "ahtm_dates_blue_pulpable_bin": "Blue bin",
    "ahtm_dates_green_organic_bin": "Green Bin",
}


class Manchester(Scraper):
    meta = Meta(
        title="Manchester",
        url="https://www.manchester.gov.uk/bincollections",
        lads=("E08000003",),
        cases={},
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        auth_response = await http.get(_AUTH_URL)
        auth_token = auth_response.headers["Authorization"]

        post_data = {
            "name": "sr_bin_coll_day_checker",
            "data": {
                "uprn": address.need("uprn"),
                "nextCollectionFromDate": (datetime.now() - timedelta(days=1)).strftime(
                    "%Y-%m-%d"
                ),
                "nextCollectionToDate": (datetime.now() + timedelta(days=30)).strftime(
                    "%Y-%m-%d"
                ),
            },
            "email": "",
            "caseid": "",
            "xref": "",
            "xref1": "",
            "xref2": "",
        }
        headers = {
            "referer": "https://manchester.portal.uk.empro.verintcloudservices.com/",
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": auth_token,
        }
        response = await http.post(
            _API_URL,
            content=json.dumps(post_data),
            headers=headers,
        )

        collections = []
        for key, value in response.json()["data"].items():
            if not key.startswith("ahtm_dates_"):
                continue
            bin_type = _COLLECTION_MAP.get(key)
            if bin_type is None:
                continue
            for date_text in value.split(";"):
                if date_text.strip():
                    day = datetime.strptime(date_text.strip(), "%d/%m/%Y %H:%M:%S").date()
                    collections.append(Collection(day, bin_type))
        return collections


SCRAPER = Manchester()
