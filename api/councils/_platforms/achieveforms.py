"""AchieveForms (Firmstep) session and lookup helpers.

Every `*.achieveservice.com` / `my.<council>.gov.uk` portal runs the same two
steps:

1. `init_session`: load the service page, then ask `authapi/isauthenticated`
   for a session id (`auth-session`), optionally poking an `apibroker/domain`
   URL that primes it. (A few portals print the session id in the page
   instead: scrape it and skip this step.)
2. `run_lookup`: POST `apibroker/runLookup?id=<lookup id>` with
   `{"formValues": ...}` and the session id. The lookup ids and form fields are
   baked into each council's form, and so is what the reply holds, so this is a
   helper module rather than a `Scraper` subclass.

A reply comes in one of two shapes, read by `rows`/`first_row` (JSON
`integration.transformed.rows_data`) or `data_rows` (the `data` XML string).
"""

from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import Any

from api.councils._base import Http, UpstreamError

DEFAULT_TIMEOUT = 30.0


async def init_session(
    http: Http,
    initial_url: str | None,
    auth_url: str,
    hostname: str,
    *,
    uri: str | None = None,
    domain_url: str | None = None,
    auth_test_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Open the service page and return the AchieveForms session id (`sid`).

    `initial_url` is the page to load first (None: skip it, and give `uri`).
    `uri` is the page the session is asked for, by default where `initial_url`
    ended up. `domain_url` (`.../apibroker/domain/<host>`) is poked, with a
    `_` timestamp, before the session is requested; `auth_test_url` after it,
    with the `sid`.
    """
    if initial_url is not None:
        r = await http.get(initial_url, timeout=timeout)
        uri = uri or r.url
    if uri is None:
        raise ValueError("init_session needs an initial_url or a uri")
    if domain_url is not None:
        await http.get(domain_url, params={"_": int(time.time() * 1000)}, timeout=timeout)
    r = await http.get(
        auth_url,
        params={"uri": uri, "hostname": hostname, "withCredentials": "true"},
        timeout=timeout,
    )
    try:
        sid = r.json()["auth-session"]
    except (KeyError, TypeError) as exc:
        raise UpstreamError(f"{auth_url} gave no auth-session: {r.text[:200]}") from exc
    if not isinstance(sid, str) or not sid:
        raise UpstreamError(f"{auth_url} gave an empty auth-session")

    if auth_test_url is not None:
        await http.get(auth_test_url, params={"sid": sid, "_": int(time.time() * 1000)}, timeout=timeout)
    return sid


_PAGE_SID_RE = re.compile(r"""["']auth-session["']\s*:\s*["']([^"']+)["']""")


def page_session_id(page: str, *, who: str = "the service page") -> str:
    """The session id a service page prints (`"auth-session": "..."`), for portals
    that hand it out in the page instead of via `authapi/isauthenticated`."""
    match = _PAGE_SID_RE.search(page)
    if not match:
        raise UpstreamError(f"Could not find an auth-session in {who}")
    return match.group(1)


async def run_lookup(
    http: Http,
    api_url: str,
    sid: str,
    lookup_id: str,
    form_values: Mapping[str, Any] | None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    no_retry: str = "false",
    app_name: str = "AF-Renderer::Self",
    headers: Mapping[str, str] | None = None,
    body: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
    check: bool = True,
) -> dict[str, Any]:
    """POST one lookup and return the decoded JSON reply.

    `form_values` None sends no body at all. `body` adds keys beside
    `formValues` (`formId`, `processId`, `stage_id`, `stage_name`), `params`
    adds query parameters (`api=RunLookup`), `check=False` lets an HTTP error
    status through.
    """
    r = await http.post(
        api_url,
        params={
            "id": lookup_id,
            "repeat_against": "",
            "noRetry": no_retry,
            "getOnlyTokens": "undefined",
            "log_id": "",
            "app_name": app_name,
            "_": int(time.time() * 1000),
            "sid": sid,
            **(params or {}),
        },
        json=None if form_values is None else {**(body or {}), "formValues": form_values},
        headers=headers,
        timeout=timeout,
        check=check,
    )
    return r.json()


def rows(result: Any, *, key: str | None = None) -> dict[str, Any]:
    """The `rows_data` of a lookup reply as `{row key: row}`; `{}` for no rows.

    Raises `UpstreamError` for a reply without `integration.transformed` (an
    error reply, or `{"result": "logout"}` when the session was rejected).
    `rows_data` is a dict keyed by row index, or by whatever the lookup
    declares as its key (a UPRN, a name); a list is keyed by `key` in each row
    when given, else by position.
    """
    if not isinstance(result, dict):
        raise UpstreamError(f"AchieveForms lookup answered {type(result).__name__}, not an object")
    if result.get("result") == "logout":
        raise UpstreamError("AchieveForms rejected the session (logout)")
    integration = result.get("integration")
    transformed = integration.get("transformed") if isinstance(integration, dict) else None
    if not isinstance(transformed, dict):
        raise UpstreamError(f"AchieveForms lookup reply has no integration.transformed: {str(result)[:200]}")
    if transformed.get("error"):
        raise UpstreamError(f"AchieveForms lookup failed: {str(transformed['error'])[:200]}")
    data = transformed.get("rows_data") or {}
    if isinstance(data, list):
        return {
            str(row.get(key, index) if key and isinstance(row, dict) else index): row
            for index, row in enumerate(data)
        }
    if not isinstance(data, dict):
        raise UpstreamError(f"AchieveForms rows_data is a {type(data).__name__}")
    return data


def first_row(result: Any) -> dict[str, Any] | None:
    """Row "0" of a lookup reply, None when the lookup found nothing."""
    row = rows(result).get("0")
    if row is None:
        return None
    if not isinstance(row, dict):
        raise UpstreamError(f"AchieveForms row 0 is a {type(row).__name__}, not an object")
    return row


_ROW_RE = re.compile(r"<Row\b[^>]*>(.*?)</Row>", re.DOTALL)
_RESULT_RE = re.compile(r'<result column="([^"]+)"[^>]*?(?:/>|>(.*?)</result>)', re.DOTALL)


def data_rows(result: Any) -> list[dict[str, str]]:
    """Rows of the XML in a reply's `data`: one `{column: text}` per `<Row>`.

    `[]` when the reply carries no data. Text is as sent (not stripped); an
    unparseable document (an unescaped `&`) is read by pattern instead.
    """
    if not isinstance(result, dict):
        raise UpstreamError(f"AchieveForms lookup answered {type(result).__name__}, not an object")
    if result.get("result") == "logout":
        raise UpstreamError("AchieveForms rejected the session (logout)")
    xml = result.get("data")
    if not xml:
        return []
    if not isinstance(xml, str):
        raise UpstreamError(f"AchieveForms data is a {type(xml).__name__}, not XML")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [
            {column: html.unescape(text or "") for column, text in _RESULT_RE.findall(row)}
            for row in _ROW_RE.findall(xml)
        ]
    return [{r.get("column") or "": r.text or "" for r in row.iter("result")} for row in root.iter("Row")]
