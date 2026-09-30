"""Blackpool: fetch a token, then request premise collection jobs by UPRN and postcode."""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    Transport,
    UpstreamError,
)

_API_URL = "https://api.blackpool.gov.uk/api/bartec"
_JOB_NAME_PATTERN = r"^Empty(?: Bin)?(?: \d+\w+)? ([A-Za-z &]+?)( \d+\w)?$"
_NAME_MAP = {
    "Domestic Refuse": "Grey bin or Red sack",
    "Dry Recycling": "Blue bin",
    "Paper & Card": "Paper & Card",
    "Food Caddy": "Food Caddy",
}


class Blackpool(Scraper):
    meta = Meta(
        title="Blackpool Council",
        url="https://blackpool.gov.uk",
        lads=("E06000009",),
        cases={
            "Test1": {"postcode": "FY1 4DZ", "uprn": "100010802829"},
            "Test2": {"postcode": "FY3 9RQ", "uprn": "100010842301"},
            "Test3": {"postcode": "FY1 2HR", "uprn": "100012606962"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r0 = await http.get(f"{_API_URL}/security/token")
        token_match = re.search(r"<string[^>]*>(.*?)</string>", r0.text, re.DOTALL)
        token = token_match.group(1).strip() if token_match else r0.text.strip('"')

        payload = {
            "UPRN": address.need("uprn"),
            "USRN": "",
            "PostCode": address.need("postcode"),
            "StreetNumber": "",
            "CurrentUser": {
                "UserId": "",
                "Token": token,
            },
        }
        r1 = await http.post(f"{_API_URL}/collection/PremiseJobs", json=payload)

        data = r1.json()
        jobs = data.get("jobsField") or []
        if not jobs:
            message = (data.get("errorsField") or {}).get("messageField")
            if message:
                raise UpstreamError(f"Blackpool API error: {message}")

        collections = []
        for job in jobs:
            name_field = job["jobField"]["nameField"]
            match = re.search(_JOB_NAME_PATTERN, name_field)
            if not match:
                continue
            job_name = match.group(1).strip()
            collections.append(
                Collection(
                    date=datetime.strptime(
                        job["jobField"]["scheduledStartField"],
                        "%Y-%m-%dT%H:%M:%S",
                    ).date(),
                    type=_NAME_MAP.get(job_name, job_name),
                )
            )

        return collections


SCRAPER = Blackpool()
