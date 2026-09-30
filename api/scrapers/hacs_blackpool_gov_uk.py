import re
from datetime import datetime

from api.compat.curl_cffi_fallback import AsyncClient as _CurlCffiClient
from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]

TITLE = "Blackpool Council"
DESCRIPTION = "Source for blackpool.gov.uk services for Blackpool Council, UK."
URL = "https://blackpool.gov.uk"
TEST_CASES = {
    "Test1": {"postcode": "FY1 4DZ", "uprn": "100010802829"},
    "Test2": {"postcode": "FY3 9RQ", "uprn": "100010842301"},
    "Test3": {"postcode": "FY1 2HR", "uprn": 100012606962},
}

API_URL = "https://api.blackpool.gov.uk/api/bartec"
REGEX_JOB_NAME = r"^Empty(?: Bin)?(?: \d+\w+)? ([A-Za-z &]+?)( \d+\w)?$"
NAME_MAP = {
    "Domestic Refuse": "Grey bin or Red sack",
    "Dry Recycling": "Blue bin",
    "Paper & Card": "Paper & Card",
    "Food Caddy": "Food Caddy",
}
ICON_MAP = {
    "Domestic Refuse": Icons.GENERAL_WASTE,
    "Dry Recycling": Icons.RECYCLING,
    "Brown Sack": Icons.NEWSPAPER,
    "Paper & Card": Icons.PAPER,
    "Green Waste": Icons.GARDEN,
    "Food Caddy": Icons.BIO_KITCHEN,
}


class Source:
    def __init__(self, postcode, uprn):
        self._postcode = str(postcode)
        self._uprn = str(uprn)

    async def fetch(self):
        # GET request returns token (XML: <string ...>TOKEN</string>)
        s = _CurlCffiClient(follow_redirects=True)
        r0 = await s.get(f"{API_URL}/security/token")
        r0.raise_for_status()
        token_match = re.search(r"<string[^>]*>(.*?)</string>", r0.text, re.DOTALL)
        token = (
            token_match.group(1).strip() if token_match else r0.text.strip('"')
        )

        # POST request returns schedule for matching postcode/uprn
        payload = {
            "UPRN": self._uprn,
            "USRN": "",
            "PostCode": self._postcode,
            "StreetNumber": "",
            "CurrentUser": {
                "UserId": "",
                "Token": token,
            },
        }
        r1 = await s.post(f"{API_URL}/collection/PremiseJobs", json=payload)
        r1.raise_for_status()

        data = r1.json()
        jobs = data.get("jobsField") or []
        if not jobs:
            message = (data.get("errorsField") or {}).get("messageField")
            if message:
                raise Exception(f"Blackpool API error: {message}")

        # Extract job name and date from response
        entries = []
        for job in jobs:
            # "Empty Domestic Refuse 240L" -> "Domestic Refuse"
            name_field = job["jobField"]["nameField"]
            match = re.search(REGEX_JOB_NAME, name_field)
            if not match:
                continue
            jobName = match.group(1).strip()
            entries.append(
                Collection(
                    date=datetime.strptime(
                        job["jobField"]["scheduledStartField"],
                        "%Y-%m-%dT%H:%M:%S",
                    ).date(),
                    t=NAME_MAP.get(jobName, jobName),
                    icon=ICON_MAP.get(jobName),
                )
            )

        return entries
