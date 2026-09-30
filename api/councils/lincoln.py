"""Lincoln: AchieveForms lookup by UPRN and postcode, returning scheduled bin dates."""

from __future__ import annotations

from datetime import datetime, timedelta
from time import time_ns

from api.councils._base import Address, Collection, Http, Meta, Scraper

_AUTH_URL = "https://contact.lincoln.gov.uk/authapi/isauthenticated"
_DOMAIN_URL = "https://contact.lincoln.gov.uk/apibroker/domain/contact.lincoln.gov.uk"
_LOOKUP_URL = "https://contact.lincoln.gov.uk/apibroker/runLookup"
_HEADERS = {"user-agent": "Mozilla/5.0"}
_BIN_TYPES = (
    ("refusenextdate", "Refuse", "refuse_freq"),
    ("recyclenextdate", "Recycling", "recycle_freq"),
    ("gardennextdate", "Garden", "garden_freq"),
)


class Lincoln(Scraper):
    meta = Meta(
        title="City Of Lincoln Council",
        url="https://www.lincoln.gov.uk/",
        lads=("E07000138",),
        cases={
            "LN5 7SH": {"postcode": "LN5 7SH", "uprn": "235024846"},
            "LN2 4SA": {"postcode": "LN2 4SA", "uprn": "235042214"},
            "LN2 4EB": {"postcode": "LN2 4EB", "uprn": "235036597"},
        },
    )
    requires = frozenset({"postcode", "uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode").replace(" ", "").upper()
        postcode = postcode[:3] + " " + postcode[3:]
        uprn = address.need("uprn").zfill(12)

        sid_request = await http.get(
            _AUTH_URL,
            params={
                "uri": (
                    "https://contact.lincoln.gov.uk/AchieveForms/?mode=fill&consentMessage=yes"
                    "&form_uri=sandbox-publish://AF-Process-503f9daf-4db9-4dd8-876a-6f2029f11196/"
                    "AF-Stage-a1c0af0f-fec1-4419-80c0-0dd4e1d965c9/definition.json&process=1"
                    "&process_uri=sandbox-processes://AF-Process-503f9daf-4db9-4dd8-876a-6f2029f11196"
                    "&process_id=AF-Process-503f9daf-4db9-4dd8-876a-6f2029f11196"
                ),
                "hostname": "contact.lincoln.gov.uk",
                "withCredentials": True,
            },
            timeout=30,
        )
        sid = sid_request.json()["auth-session"]

        timestamp = time_ns() // 1_000_000
        await http.get(
            _DOMAIN_URL,
            params={"_": timestamp, "sid": sid},
            timeout=30,
        )

        timestamp = time_ns() // 1_000_000
        payload = {
            "formValues": {
                "Section 1": {
                    "chooseaddress": {"value": uprn},
                    "postcode": {"value": postcode},
                }
            }
        }
        params = {
            "id": "62aafd258f72c",
            "repeat_against": "",
            "noRetry": False,
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": "AF-Renderer::Self",
            "_": timestamp,
            "sid": sid,
        }
        schedule_request = await http.post(
            _LOOKUP_URL,
            params=params,
            json=payload,
            timeout=30,
        )

        rowdata = schedule_request.json()["integration"]["transformed"]["rows_data"]

        entries: list[Collection] = []
        for row_uprn, data in rowdata.items():
            if row_uprn != uprn:
                continue
            for key, bin_type, frequency_key in _BIN_TYPES:
                if not data[key]:
                    continue
                offsets = [0]
                if data[frequency_key] == "fortnightly":
                    offsets.extend(range(14, 365, 14))
                elif data[frequency_key] == "weekly":
                    offsets.extend(range(7, 365, 7))
                day = datetime.strptime(data[key], "%Y-%m-%d").date()
                for offset in offsets:
                    entries.append(Collection(day + timedelta(days=offset), bin_type))
        return entries


SCRAPER = Lincoln()
