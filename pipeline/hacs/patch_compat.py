#!/usr/bin/env python3
"""
patch_compat.py — Patch hacs compat shim files for async httpx.

Replaces upstream requests-based service modules with async-httpx equivalents
(SSLError, AchieveForms, FirmstepSelfService, WhitespaceWRP) and rewrites
waste_collection_schedule imports in the remaining service files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SSLERROR_REPLACEMENT = """\
import ssl

import httpx


def get_legacy_session():
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
    return httpx.AsyncClient(verify=ctx, follow_redirects=True)
"""


ACHIEVEFORMS_REPLACEMENT = '''\
"""AchieveForms (Firmstep) shared session and lookup helpers (async httpx)."""

import time

import httpx


async def init_session(
    session: httpx.AsyncClient,
    initial_url: str,
    auth_url: str,
    hostname: str,
    *,
    auth_test_url: str | None = None,
    timeout: int = 30,
) -> str:
    r = await session.get(initial_url, timeout=timeout)
    r.raise_for_status()

    params: dict[str, str] = {
        "uri": str(r.url),
        "hostname": hostname,
        "withCredentials": "true",
    }
    r = await session.get(auth_url, params=params, timeout=timeout)
    r.raise_for_status()
    sid: str = r.json()["auth-session"]

    if auth_test_url is not None:
        params_test: dict[str, str | int] = {
            "sid": sid,
            "_": int(time.time() * 1000),
        }
        r = await session.get(auth_test_url, params=params_test, timeout=timeout)
        r.raise_for_status()

    return sid


async def run_lookup(
    session: httpx.AsyncClient,
    api_url: str,
    sid: str,
    lookup_id: str,
    form_values: dict,
    *,
    timeout: int = 30,
    no_retry: str = "false",
    app_name: str = "AF-Renderer::Self",
) -> dict:
    params: dict[str, str | int] = {
        "id": lookup_id,
        "repeat_against": "",
        "noRetry": no_retry,
        "getOnlyTokens": "undefined",
        "log_id": "",
        "app_name": app_name,
        "_": int(time.time() * 1000),
        "sid": sid,
    }
    r = await session.post(
        api_url,
        params=params,
        json={"formValues": form_values},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()
'''


FIRMSTEP_REPLACEMENT = '''\
"""Firmstep Self-Service shared helpers (async httpx)."""

import json

import httpx
from bs4 import BeautifulSoup


async def get_hidden_form_inputs(
    session: httpx.AsyncClient, form_url: str, timeout: int = 30
) -> dict:
    r = await session.get(form_url, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return {
        inp["name"]: inp.get("value", "")
        for inp in soup.find_all("input", type="hidden")
        if inp.get("name")
    }


async def get_verification_token(
    session: httpx.AsyncClient, form_url: str, timeout: int = 30
) -> str:
    inputs = await get_hidden_form_inputs(session, form_url, timeout=timeout)
    token = inputs.get("__RequestVerificationToken")
    if not token:
        raise ValueError(
            f"__RequestVerificationToken not found in form response from {form_url}"
        )
    return token


async def lookup_addresses(
    session: httpx.AsyncClient,
    lookup_url: str,
    postcode: str,
    *,
    search_nlpg: str = "True",
    timeout: int = 30,
) -> dict:
    r = await session.post(
        lookup_url,
        data={"query": postcode, "searchNlpg": search_nlpg, "classification": ""},
        timeout=timeout,
    )
    r.raise_for_status()
    raw = json.loads(r.text)
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, list):
        return {
            item["Key"]: item["Value"]
            for item in raw
            if isinstance(item, dict) and "Key" in item and "Value" in item
        }
    return {}
'''


WHITESPACE_REPLACEMENT = '''\
"""Whitespace WRP portal client (async httpx)."""

import logging
from typing import Optional, Union

import httpx
from bs4 import BeautifulSoup

from api.compat.hacs.exceptions import SourceArgumentNotFound

_LOGGER = logging.getLogger(__name__)


class WhitespaceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def fetch_schedule(
        self,
        address_name_number: Union[str, int, None],
        address_postcode: str,
        *,
        address_street: Optional[str] = None,
        street_town: Optional[str] = None,
    ) -> list:
        async with httpx.AsyncClient(follow_redirects=True) as session:
            r = await session.get(self._base_url + "/")
            r.raise_for_status()
            soup = BeautifulSoup(r.text, features="html.parser")

            alink = soup.find("a", string="View my collections") or soup.find(
                "a", string="View My Collections"
            )
            if alink is None:
                alink = soup.find("a", href=lambda h: h and "seq=1" in h)
            if alink is None:
                raise ValueError(
                    "Initial WRP page did not load correctly – could not find collections link"
                )

            next_url = alink["href"].replace("seq=1", "seq=2")

            data = {
                "address_name_number": address_name_number,
                "address_postcode": address_postcode,
            }
            if address_street is not None:
                data["address_street"] = address_street
            if street_town is not None:
                data["street_town"] = street_town

            r = await session.post(next_url, data=data)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, features="html.parser")

            property_list = soup.find("div", id="property_list")
            alink = property_list.find("a") if property_list else None
            if alink is None:
                raise SourceArgumentNotFound(
                    "address_name_number",
                    address_name_number,
                )

            href = alink["href"]
            if not href.startswith("http"):
                href = self._base_url + "/" + href.lstrip("/")

            r = await session.get(href)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, features="html.parser")

            if soup.find("span", id="waste-hint"):
                raise SourceArgumentNotFound(
                    "address_name_number",
                    address_name_number,
                )

            scheduled = soup.find("section", id="scheduled-collections")
            if scheduled is None:
                raise ValueError(
                    "Could not find scheduled-collections section on WRP page"
                )

            results = []
            for u1 in scheduled.find_all("u1"):
                lis = u1.find_all("li", recursive=False)
                if len(lis) < 3:
                    continue

                date_li = lis[1]
                type_li = lis[2]

                date_p = date_li.find("p")
                date_text = (
                    date_p.text.strip()
                    if date_p
                    else date_li.text.replace("\\n", "").strip()
                )

                type_p = type_li.find("p")
                type_text = (
                    type_p.text.strip()
                    if type_p
                    else type_li.text.replace("\\n", "").strip()
                )

                if date_text:
                    results.append((date_text, type_text))

            return results
'''


FULL_REPLACEMENTS: dict[str, str] = {
    "SSLError.py": SSLERROR_REPLACEMENT,
    "AchieveForms.py": ACHIEVEFORMS_REPLACEMENT,
    "FirmstepSelfService.py": FIRMSTEP_REPLACEMENT,
    "WhitespaceWRP.py": WHITESPACE_REPLACEMENT,
}


def _patch_imports(file_path: Path) -> None:
    """Rewrite waste_collection_schedule and requests imports in a compat file."""
    if not file_path.exists():
        return
    source = file_path.read_text()
    original = source
    source = source.replace(
        "from waste_collection_schedule import Collection",
        "from api.compat.hacs import Collection",
    )
    source = source.replace(
        "from waste_collection_schedule.exceptions import",
        "from api.compat.hacs.exceptions import",
    )
    # Upstream increasingly uses curl_cffi's requests-compatible API
    # (e.g. `from curl_cffi import requests`). That must keep working as-is —
    # only rewrite a standalone `import requests` line, never the tail of a
    # `from ... import requests`, and leave its Session() calls alone.
    if "curl_cffi" not in source:
        source = re.sub(
            r"^import requests\s*$", "import httpx", source, flags=re.MULTILINE
        )
        source = source.replace(
            "requests.Session()", "httpx.Client(follow_redirects=True)"
        )
    if source != original:
        file_path.write_text(source)
        print(f"  Patched imports in {file_path}")


def patch(wcs_dir: Path) -> None:
    service_dir = wcs_dir / "service"

    for name, replacement in FULL_REPLACEMENTS.items():
        target = service_dir / name
        if target.exists() or replacement is SSLERROR_REPLACEMENT:
            target.write_text(replacement)
            print(f"  Replaced {target}")
        else:
            print(f"  Warning: {target} not found, skipping")

    for py_file in sorted(service_dir.glob("*.py")):
        if py_file.name in FULL_REPLACEMENTS or py_file.name == "__init__.py":
            continue
        _patch_imports(py_file)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <wcs_dir>", file=sys.stderr)
        return 1

    wcs_dir = Path(sys.argv[1])
    if not wcs_dir.is_dir():
        print(f"Error: {wcs_dir} is not a directory", file=sys.stderr)
        return 1

    patch(wcs_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
