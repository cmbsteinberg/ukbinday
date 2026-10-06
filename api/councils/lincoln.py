"""Lincoln: AchieveForms lookup by UPRN and postcode, returning scheduled bin dates."""

from __future__ import annotations

from datetime import datetime, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper
from api.councils._platforms.achieveforms import init_session, rows, run_lookup

_HOSTNAME = "contact.lincoln.gov.uk"
_AUTH_URL = f"https://{_HOSTNAME}/authapi/isauthenticated"
_DOMAIN_URL = f"https://{_HOSTNAME}/apibroker/domain/{_HOSTNAME}"
_LOOKUP_URL = f"https://{_HOSTNAME}/apibroker/runLookup"
_FORM_URI = (
    f"https://{_HOSTNAME}/AchieveForms/?mode=fill&consentMessage=yes"
    "&form_uri=sandbox-publish://AF-Process-503f9daf-4db9-4dd8-876a-6f2029f11196/"
    "AF-Stage-a1c0af0f-fec1-4419-80c0-0dd4e1d965c9/definition.json&process=1"
    "&process_uri=sandbox-processes://AF-Process-503f9daf-4db9-4dd8-876a-6f2029f11196"
    "&process_id=AF-Process-503f9daf-4db9-4dd8-876a-6f2029f11196"
)
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

        sid = await init_session(
            http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI, auth_test_url=_DOMAIN_URL
        )

        rowdata = rows(
            await run_lookup(
                http,
                _LOOKUP_URL,
                sid,
                "62aafd258f72c",
                {
                    "Section 1": {
                        "chooseaddress": {"value": uprn},
                        "postcode": {"value": postcode},
                    }
                },
            )
        )

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
