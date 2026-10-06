"""Welwyn Hatfield: submit the postcode and UPRN to its bin-collection form."""

from __future__ import annotations

from dateutil import parser

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    find_tag,
    soup,
)

_PAGE = "https://www.welhat.gov.uk/xfp/form/214"
_BOUNDARY = "----WebKitFormBoundaryuNcUUJl6BCDBZ9JO"


def _form_body(token: str, postcode: str, uprn: str) -> str:
    """Build the council's multipart form body."""
    return (
        f"--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"__token\"\r\n\r\n"
        f"{token}\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"page\"\r\n\r\n"
        f"492\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"locale\"\r\n\r\n"
        f"en_GB\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"q9f451fe0ca70775687eeedd1e54b359e55f7c10c_0_0\"\r\n\r\n"
        f"{postcode}\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"q9f451fe0ca70775687eeedd1e54b359e55f7c10c_1_0\"\r\n\r\n"
        f"{uprn}\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"qc3b0352c12fed5336c22352db2780a94ba369763\"\r\n\r\n"
        f"Domestic Waste Collection Service\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"q17867a1a3aa5a53e67cceb42ae4c4fa70dade69d\"\r\n\r\n"
        f"Garden Waste Collection Service\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"q0144c9059f13b2db9178a6c6fca02addc03829f5\"\r\n\r\n"
        f"Domestic Waste Sack Collection Service\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"qbaf6e9054b74213122e216f782a221f97eb98ce5\"\r\n\r\n"
        f"Recycling Collection Service\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"q5176b7585f1db820bff96c617966eb586c4b8687\"\r\n\r\n"
        f"Food Waste Collection Service\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"q90aa73493450c00b4651493354808f4e7cb26454\"\r\n\r\n"
        f"PM\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"q73adcf07adf82c347e258dcce449ad7a6104e225\"\r\n\r\n"
        f"2023-05-10\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"q8d79140ae1240f397891c65bd01c65e4c5003804\"\r\n\r\n"
        f"2023-05-06\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"q5c1829b11ffbb34009248f4706ec98c9558b5e34\"\r\n\r\n"
        f"2023-05-13\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"q38f336d0c9beb90a6345002e6d913800fb4f04fa\"\r\n\r\n"
        f"\r\n--{_BOUNDARY}\r\nContent-Disposition: form-data; name=\"next\"\r\n\r\n"
        f"Next\r\n--{_BOUNDARY}--\r\n"
    )


class WelwynHatfield(Scraper):
    meta = Meta(
        title="Welwyn Hatfield Borough Council",
        url="https://www.welhat.gov.uk/rubbish-recycling/check-bin-collection-day",
        lads=("E07000241",),
        cases={
            "test 1 - South Red": {"uprn": "100080965745", "postcode": "AL9 5EA"},
            "test 2 - Blue North": {"uprn": "100080977050", "postcode": "AL7 3ET"},
        },
    )
    requires = frozenset({"uprn", "postcode"})
    headers = {
        "Host": "www.welhat.gov.uk",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1",
        "Origin": "https://www.welhat.gov.uk",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Referer": "https://www.welhat.gov.uk/xfp/form/214",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    }

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        response = await http.get(_PAGE)
        page = soup(response.text)
        form = find_tag(page, "form", action="/xfp/form/214")
        token = find_tag(form, "input", {"name": "__token"})["value"]

        response = await http.post(
            _PAGE,
            headers={
                "Content-Type": f"multipart/form-data; boundary={_BOUNDARY}",
            },
            content=_form_body(token, address.need("postcode"), address.need("uprn")),
        )
        page = soup(response.text)
        table = page.table
        entries = []

        for row in table.tbody.find_all("tr"):
            columns = row.find_all("td")
            collection = columns[0].text.strip()
            if collection == "Food Waste Collection Service":
                collection = "food"
            elif collection == "Garden Waste Collection Service":
                collection = "garden"
            elif collection == "Recycling Collection Service":
                collection = "recycling"
            elif collection == "Domestic Waste Collection Service":
                collection = "refuse"
            else:
                collection = "unknown"
            day = parser.parse(columns[1].text.strip()).date()
            entries.append(Collection(day, collection))

        return entries


SCRAPER = WelwynHatfield()
