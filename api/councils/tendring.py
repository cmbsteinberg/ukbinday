"""Tendring: an AchieveForms lookup keyed on the UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper
from api.councils._platforms.achieveforms import data_rows, init_session, run_lookup

_HOSTNAME = "tendring-self.achieveservice.com"
_HOST = f"https://{_HOSTNAME}"
_AUTH_URL = f"{_HOST}/authapi/isauthenticated"
_FORM_URI = f"{_HOST}/en/service/Rubbish_and_recycling_collection_days"
_API_URL = f"{_HOST}/apibroker/runLookup"
_SCHEDULE_LOOKUP_ID = "6347acbadc425"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{_HOST}/fillform/?iframe_id=fillform-frame-1&db_id=",
}
_DATE_FIELDS = {
    "RefuseNextCol": "Residual waste",
    "DMRNextCol": "Mixed recycling",
    "PaperNextCol": "Paper and card",
    "FoodNextCol": "Food waste",
    "GardenNextCol": "Garden waste",
}


class Tendring(Scraper):
    meta = Meta(
        title="Tendring District Council",
        url="https://www.tendring.gov.uk",
        lads=("E07000076",),
        cases={"Test_001": {"uprn": "100090604247"}},
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        sid = await init_session(http, None, _AUTH_URL, _HOSTNAME, uri=_FORM_URI)

        # The lookup answers {"status": "done", "data": "<Responses>...XML..."}.
        reply_rows = data_rows(
            await run_lookup(
                http,
                _API_URL,
                sid,
                _SCHEDULE_LOOKUP_ID,
                {"Select address": {"selectedUPRN": {"value": uprn}, "selectAddress": {"value": uprn}}},
                no_retry="true",
            )
        )
        if not reply_rows:
            return []  # the council lists nothing for this property
        row = reply_rows[0]

        collections = []
        for field, bin_type in _DATE_FIELDS.items():
            if field == "GardenNextCol" and row.get("ActiveGardenCollection") == "0":
                continue
            date_str = row.get(field)
            if not date_str:
                continue
            try:
                day = datetime.strptime(date_str.split()[0], "%d/%m/%Y").date()
            except (ValueError, IndexError):
                continue
            collections.append(Collection(day, bin_type))

        return collections


SCRAPER = Tendring()
