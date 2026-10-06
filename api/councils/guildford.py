"""Guildford: a Salesforce Aura request keyed by UPRN, with a framework-token retry."""

from __future__ import annotations

import json
from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper

_API_URL = (
    "https://my.guildford.gov.uk/customers/s/sfsites/aura"
    "?r=10&other.BinScheduleDisplayCmp.GetBinSchedules=1"
)
_INITIAL_FRAMEWORK = "-SjNAdgW9yv96YgKI8MiFA"


def _params(uprn: str, framework: str, *, initial: bool) -> str:
    fwuid = f"i{framework}" if initial else framework
    return (
        "message=%7B%22actions%22%3A%5B%7B%22id%22%3A%22291%3Ba%22%2C%22descriptor%22%3A%22apex%3A%2F%2FBinScheduleDisplayCmpController%2FACTION%24GetBinSchedules%22%2C%22callingDescriptor%22%3A%22markup%3A%2F%2Fc%3ABinScheduleDisplay%22%2C%22params%22%3A%7B%22database%22%3A%22domestic%22%2C%22UPRN%22%3A%22"
        + uprn
        + "%22%7D%2C%22version%22%3Anull%7D%5D%7D&aura.context=%7B%22mode%22%3A%22PROD%22%2C%22fwuid%22%3A%22"
        + fwuid
        + "%22%2C%22app%22%3A%22siteforce%3AcommunityApp%22%2C%22loaded%22%3A%7B%22APPLICATION%40markup%3A%2F%2Fsiteforce%3AcommunityApp%22%3A%22PAjEh9HEIZmsDpK-Y8SVTg%22%2C%22COMPONENT%40markup%3A%2F%2Fflowruntime%3AflowRuntimeForFlexiPage%22%3A%22mAcRFr74U2AGVmxwdG0jJw%22%7D%2C%22dn%22%3A%5B%5D%2C%22globals%22%3A%7B%22eswConfigDeveloperName%22%3Anull%2C%22isVoiceOver%22%3Anull%2C%22setupAppContextId%22%3Anull%2C%22density%22%3Anull%2C%22srcdoc%22%3Anull%2C%22appContextId%22%3Anull%2C%22dynamicTypeSize%22%3Anull%7D%2C%22uad%22%3Afalse%7D&aura.pageURI=%2Fcustomers%2Fs%2Fview-bin-collections&aura.token=null"
    )


class Guildford(Scraper):
    meta = Meta(
        title="Guildford Borough Council",
        url="https://guildford.gov.uk",
        lads=("E07000209",),
        cases={
            "GU12": {"uprn": "10007060305"},
            "GU1": {"uprn": "100061398158"},
            "GU2": {"uprn": "100061391831"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn")
        framework = _INITIAL_FRAMEWORK
        request_url = f"{_API_URL}&{_params(uprn, framework, initial=True)}"
        r = await http.post(request_url)

        if "exceptionMessage" in r.text:
            words = r.text.split(" ")
            current = 0
            while current < len(words):
                if words[current] == "Expected:":
                    framework = words[current + 1]
                    request_url = f"{_API_URL}&{_params(uprn, framework, initial=False)}"
                    r = await http.post(request_url, check=False)
                current += 1

        text = json.loads(r.text)
        schedule = text["actions"][0]["returnValue"]["FeatureSchedules"]
        collections = []

        for collection in schedule:
            if not collection.get("NextDate"):
                continue  # a service with nothing scheduled
            collections.append(
                Collection(
                    date=datetime.strptime(
                        collection["NextDate"], "%Y-%m-%dT%H:%M:%S.000Z"
                    ).date(),
                    type=collection["FeatureName"],
                )
            )

        return collections


SCRAPER = Guildford()
