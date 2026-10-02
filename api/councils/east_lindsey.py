"""East Lindsey: submits the UPRN through a session-tokenized form and reads collection dates."""

from __future__ import annotations

import base64
import datetime
import json
import re

from api.councils._base import (
    Address,
    Blocker,
    Collection,
    Http,
    InputError,
    Meta,
    Scraper,
    Transport,
)

_PAGE_URL = "https://www.e-lindsey.gov.uk/mywastecollections"
_ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)")


def _parse_date(value: str) -> datetime.date | None:
    """Parse a date such as 'Wednesday 29th April 2026'."""
    if not value:
        return None
    parts = _ORDINAL_RE.sub(r"\1", value).split()
    if len(parts) != 4:
        return None
    try:
        return datetime.datetime.strptime(
            f"{parts[1]} {parts[2]} {parts[3]}", "%d %B %Y"
        ).date()
    except ValueError:
        return None


class EastLindsey(Scraper):
    meta = Meta(
        title="East Lindsey District Council",
        url=_PAGE_URL,
        lads=("E07000137",),
        cases={"13 Firbeck Avenue, Skegness": {"uprn": "100030786099"}},
    )
    requires = frozenset({"uprn"})
    blocker = Blocker.BOT_PROTECTION  # its site blocks Vercel's IPs (scripts/vercel_probe.py)
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        # Get the form prefix and session tokens.
        r = await http.get(_PAGE_URL, timeout=30)
        html = r.text

        prefix_match = re.search(r'name="([A-Z0-9]+)_PAGESESSIONID"', html)
        if not prefix_match:
            raise InputError("Could not find the East Lindsey form prefix")
        prefix = prefix_match.group(1)

        action_match = re.search(
            r'<form[^>]+action="(https://[^"]+/processsubmission[^"]*)"', html
        )
        if not action_match:
            raise InputError("Could not find the East Lindsey form action")
        submit_url = action_match.group(1).replace("&amp;", "&")

        pagesid_match = re.search(
            rf'name="{prefix}_PAGESESSIONID"\s+value="([^"]+)"', html
        )
        sessionid_match = re.search(
            rf'name="{prefix}_SESSIONID"\s+value="([^"]+)"', html
        )
        nonce_match = re.search(rf'name="{prefix}_NONCE"\s+value="([^"]+)"', html)

        if not pagesid_match or not sessionid_match or not nonce_match:
            raise InputError("Could not extract the East Lindsey form session tokens")

        variables = base64.b64encode(
            json.dumps(
                {
                    "ADDRESSSOURCE": {
                        "value": "NLPGEL",
                        "scope": "SERVERCLIENTWITHUPDATE",
                    },
                    "ADDRESSUPRN": {
                        "value": uprn,
                        "scope": "SERVERCLIENTWITHUPDATE",
                    },
                    "TESTDATELAYOUT_DISPLAYED": {
                        "value": False,
                        "scope": "SERVERCLIENT",
                    },
                }
            ).encode()
        ).decode()

        form_data = {
            f"{prefix}_PAGESESSIONID": pagesid_match.group(1),
            f"{prefix}_SESSIONID": sessionid_match.group(1),
            f"{prefix}_NONCE": nonce_match.group(1),
            f"{prefix}_VARIABLES": variables,
            f"{prefix}_PAGENAME": "LOOKUP",
            f"{prefix}_PAGEINSTANCE": "0",
            f"{prefix}_LOOKUP_CHOSENADDRESS": uprn,
            f"{prefix}_FORMACTION_NEXT": f"{prefix}_LOOKUP_FIELD2",
        }

        r = await http.post(submit_url, data=form_data, timeout=30)

        data_match = re.search(rf"{prefix}FormData\s*=\s*\"([^\"]+)\"", r.text)
        if not data_match:
            raise InputError("No collection data found; check that the UPRN is valid")

        payload = json.loads(base64.b64decode(data_match.group(1)).decode("utf-8"))
        result_list = payload.get("RESULTS_1", {}).get("FIELD12", {}).get("result", [])
        if not result_list:
            raise InputError("No collection results found; check that the UPRN is valid")

        result = result_list[0]
        collections: list[Collection] = []
        for field, waste_type in [
            ("wastenextref", "Refuse"),
            ("wastenextrec", "Recycling"),
            ("wastenextpur", "Purple Bin"),
            ("greenfirst", "Garden Waste"),
        ]:
            day = _parse_date(result.get(field, ""))
            if day:
                collections.append(Collection(day, waste_type))

        return collections


SCRAPER = EastLindsey()
