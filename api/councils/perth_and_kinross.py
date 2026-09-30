"""Perth and Kinross: AchieveForms lookup by UPRN; one row with a date field per bin colour."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, AddressNotFound, Collection, Http, Meta, Scraper
from api.councils._platforms.achieveforms import init_session, run_lookup

_BASE_URL = "https://my.pkc.gov.uk"
_INITIAL_URL = (
    f"{_BASE_URL}/AchieveForms/?mode=fill&consentMessage=yes"
    "&form_uri=sandbox-publish://AF-Process-de9223b1-a7c6-408f-aaa3-aee33fd7f7fa/"
    "AF-Stage-9fa33e2e-4c1b-4963-babf-4348ab8154bc/definition.json"
    "&process=1"
    "&process_uri=sandbox-processes://AF-Process-de9223b1-a7c6-408f-aaa3-aee33fd7f7fa"
    "&process_id=AF-Process-de9223b1-a7c6-408f-aaa3-aee33fd7f7fa"
)
_LOOKUP_ID = "5c9267cee5efe"

# Raw date field -> waste type. Which fields are filled depends on the
# property's collection scheme.
_FIELD_MAP = {
    "nextGeneralWasteCollectionDate": "Non-recyclable waste (green-lidded bin)",
    "nextGeneralWasteCollectionDate2nd": "Non-recyclable waste (green-lidded bin)",
    "nextBlueCollectionDate": "Paper and cardboard (blue-lidded bin)",
    "nextBlueWasteCollectionDate2nd": "Paper and cardboard (blue-lidded bin)",
    "nextGreyWasteCollectionDate": "Plastic bottles, cans and cartons (grey-lidded bin)",
    "nextGreyWasteCollectionDate2nd": "Plastic bottles, cans and cartons (grey-lidded bin)",
    "nextGardenandFoodWasteCollectionDate": "Food and garden waste (brown-lidded bin)",
    "nextGardenandFoodWasteCollectionDate2nd": "Food and garden waste (brown-lidded bin)",
    "nextPaperWasteCollectionDate": "Paper and cardboard",
    "nextPaperWasteCollectionDate2nd": "Paper and cardboard",
    "nextGardenWasteCollectionDate": "Garden waste",
    "nextGardenWasteCollectionDate2nd": "Garden waste",
    "nextCommunalFoodWasteCollectionDate": "Communal food waste",
}


class PerthAndKinross(Scraper):
    meta = Meta(
        title="Perth and Kinross Council",
        url="https://www.pkc.gov.uk",
        lads=("S12000048",),
        cases={
            "7 St Marys Drive, Perth, PH2 7BY": {"uprn": "124022910"},
            "10A Crieff Road, Perth, PH1 5AF": {"uprn": "124003157"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        sid = await init_session(
            http, _INITIAL_URL, f"{_BASE_URL}/authapi/isauthenticated", "my.pkc.gov.uk"
        )
        result = await run_lookup(
            http,
            f"{_BASE_URL}/apibroker/runLookup",
            sid,
            _LOOKUP_ID,
            {"Bin collections": {"propertyUPRNQuery": {"value": uprn}}},
        )
        rows = result.get("integration", {}).get("transformed", {}).get("rows_data")
        if not isinstance(rows, dict) or not rows:
            raise AddressNotFound(f"Perth and Kinross does not know UPRN {uprn}")
        row = rows.get("0", {})
        if not row or str(row.get("returnedUPRN", "")).strip().lower() in ("", "false"):
            raise AddressNotFound(f"Perth and Kinross does not know UPRN {uprn}")

        collections = []
        for field, waste_type in _FIELD_MAP.items():
            text = str(row.get(field, "")).strip()
            if not text:
                continue
            try:
                day = datetime.strptime(text, "%d/%m/%Y").date()
            except ValueError:
                continue
            collections.append(Collection(day, waste_type))

        if not collections:
            raise AddressNotFound(f"Perth and Kinross has no collections for UPRN {uprn}")
        return collections


SCRAPER = PerthAndKinross()
