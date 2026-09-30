"""AchieveForms (Firmstep) session and lookup helpers.

Every `*.achieveservice.com` / `my.<council>.gov.uk` portal runs the same two
steps:

1. `init_session`: load the service page, then ask `authapi/isauthenticated`
   for a session id (`auth-session`), optionally poking an `apibroker/domain`
   URL that primes it.
2. `run_lookup`: POST `apibroker/runLookup?id=<lookup id>` with
   `{"formValues": ...}` and the session id. The lookup ids and form fields are
   baked into each council's form, and so is how the `rows_data` reply is read,
   so this is a helper module rather than a `Scraper` subclass.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from api.councils._base import Http

DEFAULT_TIMEOUT = 30.0


async def init_session(
    http: Http,
    initial_url: str,
    auth_url: str,
    hostname: str,
    *,
    auth_test_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Open the service page and return the AchieveForms session id (`sid`)."""
    r = await http.get(initial_url, timeout=timeout)
    r = await http.get(
        auth_url,
        params={"uri": r.url, "hostname": hostname, "withCredentials": "true"},
        timeout=timeout,
    )
    sid: str = r.json()["auth-session"]

    if auth_test_url is not None:
        await http.get(auth_test_url, params={"sid": sid, "_": int(time.time() * 1000)}, timeout=timeout)
    return sid


async def run_lookup(
    http: Http,
    api_url: str,
    sid: str,
    lookup_id: str,
    form_values: Mapping[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    no_retry: str = "false",
    app_name: str = "AF-Renderer::Self",
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """POST one lookup and return the decoded JSON reply."""
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
        },
        json={"formValues": form_values},
        headers=headers,
        timeout=timeout,
    )
    return r.json()
