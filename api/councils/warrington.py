"""Warrington: fetches bin collection jobs by UPRN from the council's bin-collections service."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, Transport

_URL = "https://www.warrington.gov.uk"
_JOBS_URL = "https://www.warrington.gov.uk/bin-collections/get-jobs"


def _get_type(name: str) -> str | None:
    if "BLACK" in name:
        return "Black Bin"
    if "BLUE" in name:
        return "Blue Bin"
    if "GREEN" in name:
        return "Green Bin"
    return None


class Warrington(Scraper):
    meta = Meta(
        title="Warrington Borough Council",
        url=_URL,
        lads=("E06000007",),
        cases={
            "Test_001": {"uprn": "100010309878"},
            "Test_002": {"uprn": "100010296572"},
            "Test_003": {"uprn": "100010291332"},
        },
    )
    requires = frozenset({"uprn"})
    # Cloudflare fronts the site; a Chrome TLS fingerprint is the cheap hope for cloud IPs.
    transport = Transport.CURL_CFFI

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        response = await http.get(f"{_JOBS_URL}/{uprn}")
        json_data = response.json()

        if not json_data["schedule"]:
            return []

        collections = []
        for job in json_data["schedule"]:
            bin_type = _get_type(job["Name"])
            if not bin_type:
                continue

            day = datetime.strptime(job["ScheduledStart"], "%Y-%m-%dT%H:00:00").date()
            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Warrington()
