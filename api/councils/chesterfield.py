"""Chesterfield: fetches a collection schedule from its Aura endpoint by UPRN."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_URLS = {
    "session": "https://www.chesterfield.gov.uk/bins-and-recycling/bin-collections/check-bin-collections.aspx",
    "fwuid": "https://myaccount.chesterfield.gov.uk/anonymous/c/cbc_VE_CollectionDaysLO.app?aura.format=JSON&aura.formatAdapter=LIGHTNING_OUT",
    "search": "https://myaccount.chesterfield.gov.uk/anonymous/aura?r=2&aura.ApexAction.execute=1",
}

_HEADERS = {"user-agent": "Mozilla/5.0"}


class Chesterfield(Scraper):
    meta = Meta(
        title="Chesterfield Borough Council",
        url="https://www.chesterfield.gov.uk/",
        lads=("E07000034",),
        cases={
            "Test_001": {"uprn": "74023685"},
            "Test_002": {"uprn": "74009625"},
            "Test_003": {"uprn": "74035689"},
        },
    )
    requires = frozenset({"uprn"})
    headers = _HEADERS
    verify_tls = False

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")

        await http.get(_URLS["session"])
        r = await http.get(_URLS["fwuid"])
        fwuid = r.json()["auraConfig"]["context"]["fwuid"]

        payload = {
            "message": (
                '{"actions":[{"id":"4;a","descriptor":"aura://ApexActionController/ACTION$execute",'
                '"callingDescriptor":"UNKNOWN","params":{"namespace":"","classname":"CBC_VE_CollectionDays",'
                '"method":"getServicesByUPRN","params":{"propertyUprn":"'
                + uprn
                + '","executedFrom":"Main Website"},"cacheable":false,"isContinuation":false}}]}'
            ),
            "aura.context": (
                '{"mode":"PROD","fwuid":"'
                + fwuid
                + '","app":"c:cbc_VE_CollectionDaysLO","loaded":'
                '{"APPLICATION@markup://c:cbc_VE_CollectionDaysLO":"pqeNg7kPWCbx1pO8sIjdLA"},'
                '"dn":[],"globals":{},"uad":true}'
            ),
            "aura.pageURI": "/bins-and-recycling/bin-collections/check-bin-collections.aspx",
            "aura.token": "null",
        }
        r = await http.post(_URLS["search"], data=payload)
        data = r.json()

        collections = []
        for item in data["actions"][0]["returnValue"]["returnValue"]["serviceUnits"]:
            try:
                waste_type = item["serviceTasks"][0]["taskTypeName"]
            except IndexError:
                # Commercial collection schedules for residential properties can be empty.
                continue

            waste_type = str(waste_type).replace("Collect ", "")
            try:
                date_text = item["serviceTasks"][0]["serviceTaskSchedules"][0]["nextInstance"][
                    "currentScheduledDate"
                ]
            except (IndexError, KeyError):
                continue

            day = datetime.strptime(date_text, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(None).date()
            collections.append(Collection(day, waste_type))

        return collections


SCRAPER = Chesterfield()
