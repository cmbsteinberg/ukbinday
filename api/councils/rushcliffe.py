"""Rushcliffe: Firmstep form. Look the postcode up, pick the property, submit, read the confirmation panel.

The panel is a run of `Your next <bin> bin ... dd/mm/yyyy` lines separated by <br/>.
"""

from __future__ import annotations

import re
from datetime import datetime

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
    match_address,
    soup,
)
from api.councils._platforms.firmstep import lookup_addresses, verification_token

_HOST = "https://selfservice.rushcliffe.gov.uk"
_FORM_PAGE = f"{_HOST}/renderform.aspx?t=1242&k=86BDCD8DE8D868B9E23D10842A7A4FE0F1023CCA"
_UPRN_FIELD = "FF3518"


class Rushcliffe(Scraper):
    meta = Meta(
        title="Rushcliffe Borough Council",
        url="https://www.rushcliffe.gov.uk/",
        lads=("E07000176",),
        cases={
            "NG12 5FE 2 Church Drive": {
                "postcode": "NG12 5FE",
                "house_number": "2",
                "street": "Church Drive",
                "address": "2 Church Drive, Keyworth, NOTTINGHAM, NG12 5FE",
            }
        },
    )
    requires = frozenset({"postcode"})
    headers = {"User-Agent": "Mozilla/5.0", "Host": "selfservice.rushcliffe.gov.uk"}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        postcode = address.need("postcode")
        token = await verification_token(http, _FORM_PAGE)
        addresses = await lookup_addresses(http, f"{_HOST}/core/addresslookup", postcode)
        key, label = match_address(
            address,
            addresses.items(),
            text=lambda item: item[1],
            uprn=lambda item: item[0].strip().upper().removeprefix("U"),
        )

        r = await http.post(
            f"{_HOST}/renderform/Form",
            data={
                "FormGuid": "aaa360e6-240e-46e9-b651-bd7fb8091354",
                "ObjectTemplateID": "1242",
                "Trigger": "submit",
                "CurrentSectionID": 1397,
                "TriggerCtl": "",
                "__RequestVerificationToken": token,
                _UPRN_FIELD: key,
                _UPRN_FIELD + "lbltxt": address.label or label,
                # sic: the old scraper built this name by doubling the field id
                _UPRN_FIELD + _UPRN_FIELD + "-text": postcode,
            },
        )
        panel = soup(r.text).find("div", {"class": "ss_confPanel"})
        if not panel:
            raise UpstreamError("Rushcliffe returned no collection panel")

        lines = str(panel).replace("<b>", "").replace("</b>", "")
        collections = []
        for raw in lines.split("<br/>"):
            line = raw.strip()
            if not line.startswith("Your"):
                continue
            bin_type = line.split(" bin", 1)[0].replace("Your next ", "").split("(", 1)[0].strip()
            for text in re.findall(r"\d{2}/\d{2}/\d{4}", line):
                collections.append(Collection(datetime.strptime(text, "%d/%m/%Y").date(), bin_type))
        return collections


SCRAPER = Rushcliffe()
