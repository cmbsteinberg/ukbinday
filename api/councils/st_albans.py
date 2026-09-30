"""St Albans: a UPRN-keyed API returns service headers and their last and next collection dates."""

from __future__ import annotations

from datetime import datetime

from api.councils._base import Address, Collection, Http, Meta, Scraper, UpstreamError

_API_URL = (
    "https://gis.stalbans.gov.uk/NoticeBoard9/VeoliaProxy.NoticeBoard.asmx/"
    "GetServicesByUprnAndNoticeBoard"
)


class StAlbans(Scraper):
    meta = Meta(
        title="St Albans City & District Council",
        url="https://stalbans.gov.uk",
        lads=("E07000240",),
        cases={
            "55 St John's Ct": {"uprn": "100081132201"},
            "9 Tyttenhanger Grn": {"uprn": "100080869141"},
        },
    )
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        r = await http.post(
            _API_URL,
            json={"noticeBoard": "default", "uprn": address.need("uprn")},
        )
        data = r.json()
        if not isinstance(data, dict) or "d" not in data or not isinstance(data["d"], list):
            raise UpstreamError("Got invalid response from API")

        collections: list[Collection] = []
        for entry in data["d"]:
            if not isinstance(entry, dict):
                continue

            headers = entry.get("ServiceHeaders")
            if not isinstance(headers, list):
                continue

            for header in headers:
                if not isinstance(header, dict):
                    continue

                bin_type = header.get("TaskType")
                if not bin_type or not isinstance(bin_type, str):
                    continue
                bin_type = bin_type.removeprefix("Collect ")

                for date_key in ("Last", "Next"):
                    date_str = header.get(date_key)
                    if not date_str or not isinstance(date_str, str):
                        continue
                    day = datetime.strptime(date_str.split("T")[0], "%Y-%m-%d").date()
                    collections.append(Collection(day, bin_type))

        return collections


SCRAPER = StAlbans()
