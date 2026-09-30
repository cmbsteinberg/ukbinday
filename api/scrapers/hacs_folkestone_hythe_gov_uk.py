import re
from datetime import datetime

from bs4 import BeautifulSoup

from api.compat.curl_cffi_fallback import AsyncClient as _CurlCffiClient
from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]

TITLE = "Folkestone and Hythe District Councol"
DESCRIPTION = "Source for Folkestone and Hythe District Council, United Kingdom."
URL = "https://www.folkestone-hythe.gov.uk/"
TEST_CASES = {
    "Folkestone_Test": {"uprn": 50032102},
    "Hythe_Test": {"uprn": "50019287"},
}
ICON_MAP = {
    "Non-Recyclables (Green Lid) and Food Waste": Icons.BIO_KITCHEN,
    "Recycling (Purple Lid / Black Box and Food Waste)": Icons.BIO_KITCHEN,
    "General Waste": Icons.GENERAL_WASTE,
    "Food Waste": Icons.BIO_KITCHEN,
    "Paper & Card": Icons.PAPER,
    "Recycling (mixed)": Icons.RECYCLING,
    "Communal General Waste": Icons.GENERAL_WASTE,
    "Communal Food Waste": Icons.BIO_KITCHEN,
    "Communal Recycling (mixed)": Icons.RECYCLING,
    "Communal Paper & Card": Icons.PAPER,
}
REGEX_ORDINALS = r"(?<=\d)(st|nd|rd|th)"


class Source:
    def __init__(self, uprn: str | int):
        self._uprn = str(uprn)

    async def fetch(self):
        s = _CurlCffiClient(follow_redirects=True)
        index_url = f"https://service.folkestone-hythe.gov.uk/webapp/myarea/index.php?uprn={self._uprn}"
        # Collections are loaded via AJAX; the index page only renders a
        # "Fetching collection dates" placeholder. Prime the session, then
        # hit the same endpoint the site's JS uses (requires Referer).
        r0 = await s.get(index_url)
        r0.raise_for_status()
        r = await s.get(
            f"https://service.folkestone-hythe.gov.uk/webapp/myarea/api_collections.php?uprn={self._uprn}",
            headers={"X-Requested-With": "fetch", "Referer": index_url},
        )
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        entries = []

        for card in soup.select("article.service-card"):
            title = card.select_one("h3.service-title")
            when = card.select_one("p.service-next time[datetime]")
            if title is None or when is None or not when.get("datetime"):
                continue
            entries.append(
                Collection(
                    date=datetime.fromisoformat(when["datetime"]).date(),
                    t=title.get_text(strip=True),
                    icon=ICON_MAP.get(title.get_text(strip=True)),
                )
            )

        if not entries:
            raise Exception(f"No collections found for UPRN {self._uprn}")

        return entries
