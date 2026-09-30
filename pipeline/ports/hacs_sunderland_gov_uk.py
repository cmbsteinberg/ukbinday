import re
from datetime import datetime

from bs4 import BeautifulSoup

from api.compat.curl_cffi_fallback import AsyncClient as _CurlCffiClient
from api.compat.hacs import Collection, Icons  # type: ignore[attr-defined]
from api.compat.hacs.exceptions import (
    SourceArgumentNotFound,
    SourceArgumentNotFoundWithSuggestions,
)

TITLE = "Sunderland City Council"
DESCRIPTION = "Source for sunderland.gov.uk services for Sunderland City Council, UK."
URL = "https://www.sunderland.gov.uk/"
PAGE_URL = "https://www.sunderland.gov.uk/bindays"
FORM_PREFIX = "BINCOLLECTIONCHECKERNEWV3"
HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

TEST_CASES = {
    "Test_001": {"postcode": "SR4 7PU", "address": "191 Cleveland Road"},
    "Test_002": {"postcode": "SR3 2DW", "address": "43 Hill Street"},
    "Test_003": {"postcode": "SR4 8RJ", "address": "17 Sutherland Drive"},
}

ICON_MAP = {
    "Household Green Bin": Icons.GENERAL_WASTE,
    "Blue Recycling Bin": Icons.RECYCLING,
    "Garden Waste": Icons.GARDEN,
}


class Source:
    def __init__(
        self,
        postcode: str,
        address: str = "",
        house_number: str = "",
        street: str = "",
    ):
        self._postcode = str(postcode).strip()
        self._address = str(address).strip()
        self._house_number = str(house_number).strip()
        self._street = str(street).strip()

    def _get_hidden_fields(self, soup: BeautifulSoup) -> dict:
        """Extract hidden input fields whose name starts with FORM_PREFIX."""
        fields = {}
        for tag in soup.find_all("input", type="hidden"):
            name = tag.get("name", "")
            if name.startswith(FORM_PREFIX):
                fields[name] = tag.get("value", "")
        return fields

    def _get_submit_url(self, soup: BeautifulSoup) -> str:
        """Extract the processsubmission URL from the form action."""
        form = soup.find("form", id=f"{FORM_PREFIX}_FORM")
        if form and form.get("action"):
            return form["action"]
        raise ValueError("Could not find form action URL in page")

    async def fetch(self):
        s = _CurlCffiClient(follow_redirects=True)
        s.headers.update(HEADERS)

        # Step 1: GET the bin checker page to obtain session IDs and nonce
        r = await s.get(PAGE_URL)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")

        fields = self._get_hidden_fields(soup)
        submit_url = self._get_submit_url(soup)

        # Step 2: POST postcode to trigger address lookup
        payload = dict(fields)
        payload.update(
            {
                f"{FORM_PREFIX}_PAGENAME": "ADDRESSSEARCH",
                f"{FORM_PREFIX}_PAGEINSTANCE": "0",
                f"{FORM_PREFIX}_ADDRESSSEARCH_SCCPOSTCODE": self._postcode,
                f"{FORM_PREFIX}_FORMACTION_NEXT": f"{FORM_PREFIX}_ADDRESSSEARCH_POSTCODETRIGGER",
                f"{FORM_PREFIX}_ADDRESSSEARCH_SCCLISTOFADDRESSES": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_POSTCODE": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_UPRN": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_RESIDUALBIN": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_TRADEBIN": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_RECYCLEBIN": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_GARDENBIN": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_NEXTBIN": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_PDFURL": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_LAT": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_LNG": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_ADDRESSTEXT": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_DATARETURNED": "",
                f"{FORM_PREFIX}_ADDRESSSEARCH_DATARETURNED2": "",
            }
        )

        r = await s.post(submit_url, data=payload, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")

        # Step 3: Extract address list from the SCCLISTOFADDRESSES <select>.
        # Option values are internal ids, which the final POST expects as the UPRN field.
        fields = self._get_hidden_fields(soup)
        submit_url = self._get_submit_url(soup)

        select = soup.find(
            "select", {"name": f"{FORM_PREFIX}_ADDRESSSEARCH_SCCLISTOFADDRESSES"}
        )
        address_options = [
            (o.get("value", ""), o.get_text(strip=True))
            for o in (select.find_all("option") if select else [])
            if o.get("value")
        ]
        if not address_options:
            raise SourceArgumentNotFound(
                "postcode",
                self._postcode,
                "no addresses were returned, please check the postcode is correct.",
            )

        def normalise(s: str) -> str:
            return re.sub(r"[\s,]+", " ", s).strip().lower()

        # Candidate search strings, most specific first
        candidates = []
        if self._house_number and self._street:
            candidates.append(f"{self._house_number} {self._street}")
        if self._address:
            candidates.append(self._address)
            parts = [p for p in self._address.split(",") if p.strip()]
            if len(parts) > 2:
                candidates.append(" ".join(parts[:2]))

        uprn = None
        matched_address = None
        for cand in candidates:
            n = normalise(cand)
            for value, text in address_options:
                nt = normalise(text)
                if nt == n or nt.startswith(n + " ") or n in nt:
                    uprn, matched_address = value, text
                    break
            if uprn:
                break

        if uprn is None:
            raise SourceArgumentNotFoundWithSuggestions(
                "address",
                self._address or f"{self._house_number} {self._street}".strip(),
                [t for _, t in address_options],
            )

        # Step 4: POST with selected UPRN to retrieve collection dates
        payload = dict(fields)
        payload.update(
            {
                f"{FORM_PREFIX}_PAGENAME": "ADDRESSSEARCH",
                f"{FORM_PREFIX}_PAGEINSTANCE": "1",
                f"{FORM_PREFIX}_ADDRESSSEARCH_SCCPOSTCODE": self._postcode,
                f"{FORM_PREFIX}_FORMACTION_NEXT": f"{FORM_PREFIX}_ADDRESSSEARCH_POSTCODETRIGGER",
                f"{FORM_PREFIX}_ADDRESSSEARCH_SCCLISTOFADDRESSES": uprn,
                f"{FORM_PREFIX}_ADDRESSSEARCH_POSTCODE": self._postcode,
                f"{FORM_PREFIX}_ADDRESSSEARCH_UPRN": uprn,
                f"{FORM_PREFIX}_ADDRESSSEARCH_ADDRESSTEXT": matched_address,
            }
        )

        r = await s.post(submit_url, data=payload, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")

        # Step 5: Parse collection dates from results page
        # Dates appear in <p class="myaccount-block__date--bin--waste"> as "Fri Jun 19 2026"
        entries = []
        for bin_type, icon in ICON_MAP.items():
            # Find the title element for this bin type
            title_el = soup.find(
                "p",
                string=re.compile(re.escape(bin_type), re.IGNORECASE),
            )
            if title_el is None:
                continue

            # The date is in a sibling <p> with class containing "myaccount-block__date"
            container = title_el.parent
            date_el = container.find("p", class_=re.compile(r"myaccount-block__date"))
            if date_el is None:
                continue

            date_str = date_el.get_text(strip=True)
            try:
                # Format: "Fri Jun 19 2026"
                date = datetime.strptime(date_str, "%a %b %d %Y").date()
                entries.append(Collection(date=date, t=bin_type, icon=icon))
            except ValueError:
                continue

        if not entries:
            raise ValueError(
                "No collection dates could be parsed from the Sunderland bindays "
                "portal. The website structure may have changed."
            )

        return entries
