"""Highland: AchieveForms lookup by UPRN; one row holds `<Type>NextDate` (old or new scheme) per bin.

With `predict=true` the frequency field is used to extend each bin ten weeks ahead.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError
from api.councils._platforms.achieveforms import init_session, run_lookup

_BASE_URL = "https://highland-self.achieveservice.com"
_HOSTNAME = "highland-self.achieveservice.com"


class Highland(Scraper):
    meta = Meta(
        title="Highland",
        url="https://www.highland.gov.uk/",
        lads=("S12000017",),
        cases={
            "Allangrange Mains Road, Black Isle": {"uprn": "130108578", "predict": "true"},
            "Quarry Lane, Tain": {"uprn": "130007199"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        predict = address.extra.get("predict", "").lower() in ("1", "true", "yes")
        sid = await init_session(
            http,
            f"{_BASE_URL}/en/service/Check_your_household_bin_collection_days",
            f"{_BASE_URL}/authapi/isauthenticated",
            _HOSTNAME,
        )
        result = await run_lookup(
            http,
            f"{_BASE_URL}/apibroker/runLookup",
            sid,
            "660d44a698632",
            {"Your address": {"propertyuprn": {"value": address.need("uprn")}}},
        )
        row = result["integration"]["transformed"]["rows_data"]["0"]
        if not isinstance(row, dict):
            raise UpstreamError("Highland returned invalid data")

        use_new = any(k.endswith("New") and v for k, v in row.items())
        next_date_key = "NextDateNew" if use_new else "NextDateOld"

        collections = []
        for key, value in row.items():
            if not key.endswith(("NextDate", next_date_key)):
                continue
            bin_type = key.split("NextDate")[0]
            try:
                day = datetime.fromisoformat(value).date()
            except ValueError:
                continue
            collections.append(Collection(day, bin_type))

            freq_key = key.replace("NextDate", "Frequency")
            if not predict or freq_key not in row:
                continue
            freq = row[freq_key]
            if not freq or not isinstance(freq, str):
                continue
            freq = freq.lower().replace("every week", "every 1 weeks")
            freq = freq.replace("every ", "").replace(" weeks", "")
            if not freq.isdigit():
                continue
            weeks = int(freq)
            for i in range(int(10 * (1 / weeks))):
                collections.append(Collection(day + timedelta(weeks=i * weeks), bin_type))
        return collections


SCRAPER = Highland()
