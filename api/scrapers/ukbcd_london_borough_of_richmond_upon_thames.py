from __future__ import annotations
import re
import html as html_unescape
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import httpx
from api.compat.ukbcd.common import date_format
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass
from api.services.browser_pool import get as _get_browser_pool

class CouncilClass(AbstractGetBinDataClass):
    """
    Richmond upon Thames – parse the static My Property page.
    No Selenium. No BeautifulSoup. Just requests + regex tailored to the current markup.
    """

    def parse_data(self, page: str, **kwargs) -> dict:
        base_url = kwargs.get('url') or page
        pid_arg = kwargs.get('pid')
        paon = kwargs.get('paon')
        pid_from_url = self._pid_from_url(base_url)
        pid_from_paon = self._pid_from_paon(paon)
        if 'pid=' in (base_url or ''):
            target_url = base_url
        elif pid_arg or pid_from_paon:
            pid = pid_arg or pid_from_paon
            sep = '&' if '?' in (base_url or '') else '?'
            target_url = f'{base_url}{sep}pid={pid}'
        else:
            raise ValueError('Richmond: supply a URL that already has ?pid=... OR put PID in the House Number field.')
        html = self._fetch_html(target_url)
        bindata = self._parse_html_for_waste(html)
        if not bindata['bins']:
            raise RuntimeError('Richmond: no bins found in page HTML.')
        return bindata

    def _fetch_html(self, url: str) -> str:
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'}
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.text

    def _parse_html_for_waste(self, html: str) -> dict:
        waste_block = self._extract_waste_block(html)
        if not waste_block:
            return {'bins': []}
        bins = []
        for h_match in re.finditer('<h4>(.*?)</h4>', waste_block, flags=re.I | re.S):
            bin_name = self._clean(h_match.group(1))
            if not bin_name:
                continue
            start = h_match.end()
            next_h = re.search('<h4>', waste_block[start:], flags=re.I)
            if next_h:
                section = waste_block[start:start + next_h.start()]
            else:
                section = waste_block[start:]
            date_lines = []
            ul_match = re.search('<ul[^>]*>(.*?)</ul>', section, flags=re.I | re.S)
            if ul_match:
                ul_inner = ul_match.group(1)
                for li in re.findall('<li[^>]*>(.*?)</li>', ul_inner, flags=re.I | re.S):
                    text = self._clean(li)
                    if text:
                        date_lines.append(text)
            if not date_lines:
                p_match = re.search('<p[^>]*>(.*?)</p>', section, flags=re.I | re.S)
                if p_match:
                    text = self._clean(p_match.group(1))
                    if text:
                        date_lines.append(text)
            col_date = self._first_date_or_message(date_lines)
            if col_date:
                bins.append({'type': bin_name, 'collectionDate': col_date})
        return {'bins': bins}

    def _extract_waste_block(self, html: str) -> str | None:
        m = re.search('<a\\s+id=["\\\']my_waste["\\\']\\s*></a>(.+?)(?:<a\\s+id=["\\\']my_parking["\\\']|<a\\s+id=["\\\']my_councillors["\\\'])', html, flags=re.I | re.S)
        if not m:
            return None
        return m.group(1)

    def _pid_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        try:
            q = parse_qs(urlparse(url).query)
            return q.get('pid', [None])[0]
        except Exception:
            return None

    def _pid_from_paon(self, paon) -> str | None:
        if paon and str(paon).isdigit() and (10 <= len(str(paon)) <= 14):
            return str(paon)
        return None

    def _clean(self, s: str) -> str:
        s = re.sub('<br\\s*/?>', ' ', s, flags=re.I)
        s = re.sub('<[^>]+>', '', s)
        s = html_unescape.unescape(s)
        return ' '.join(s.split())

    def _first_date_or_message(self, lines) -> str | None:
        date_rx = re.compile('(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\\s+)?(\\d{1,2}\\s+[A-Za-z]+\\s+\\d{4})')
        for line in lines:
            m = date_rx.search(line)
            if m:
                ds = m.group(0)
                fmt = '%A %d %B %Y' if m.group(1) else '%d %B %Y'
                dt = datetime.strptime(ds, fmt)
                return dt.strftime(date_format)
            lower = line.lower()
            if 'no collection' in lower or 'no contract' in lower or 'no subscription' in lower:
                return line
        return None

# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Richmond upon Thames"
URL = "https://www.richmond.gov.uk/services/waste_and_recycling/collection_days/"
TEST_CASES = {}


class Source:
    def __init__(self, house_number: str | None = None):
        self.house_number = house_number
        self._scraper = CouncilClass()

    async def fetch(self) -> list[Collection]:
        from datetime import datetime

        kwargs = {}
        if self.house_number: kwargs['paon'] = self.house_number

        data = await self._scraper.parse_data("", **kwargs)

        entries = []
        if isinstance(data, dict) and "bins" in data:
            for item in data["bins"]:
                bin_type = item.get("type")
                date_str = item.get("collectionDate")
                if not bin_type or not date_str:
                    continue
                try:
                    if "-" in date_str:
                        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                    elif "/" in date_str:
                        dt = datetime.strptime(date_str, "%d/%m/%Y").date()
                    else:
                        continue
                    entries.append(Collection(date=dt, t=bin_type, icon=None))
                except ValueError:
                    continue
        return entries
