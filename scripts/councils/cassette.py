"""Record and replay a council module's HTTP exchanges, for offline parser tests.

A cassette (tests/cassettes/<module>/<case>.json) holds the params, the date it
was recorded, every exchange the module made and the parsed `(date, type)` list
(the golden output). Replay swaps the `Http` backend (via `http.INTERCEPT`, so
modules never know) and freezes today to the recording date.

Matching is on method + URL + params + body, first exactly, then with volatile
values masked (session ids, CSRF tokens, epoch stamps, timestamps). A request
with no match raises `CassetteMiss`.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import time_machine

from api.councils._base import Scraper, run
from api.councils._base.http import INTERCEPT, Cookies, Http, Response

CASSETTES = Path(__file__).resolve().parents[2] / "tests" / "cassettes"
BLOBS = CASSETTES / "_blobs"
# Response headers kept: enough for redirects, cookies, charset and bot-wall detection.
KEEP_HEADERS = ("content-type", "content-disposition", "location", "set-cookie", "server", "cf-mitigated", "x-iinfo")

_NAME = r"(?:_|sid|sessionid|session_id|jsessionid|phpsessid|aspsessionid\w*|csrf\w*|xsrf\w*|token|\w*_token|__requestverificationtoken|__viewstate\w*|__eventvalidation)"
KEYS = re.compile(_NAME, re.IGNORECASE)
MASKS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-{8,}[\w-]*\d{10,}\w*"), "<boundary>"),  # multipart boundaries built from the clock
    (re.compile(rf"(?i)((?:^|[?&;\s]){_NAME}=)[^&;\s\"']*"), r"\1<masked>"),
    (re.compile(rf"(?i)(\"{_NAME}\"\s*:\s*\")[^\"]*"), r"\1<masked>"),
    (re.compile(rf"(?i)(name=[\"']{_NAME}[\"'][^>]*?value=[\"'])[^\"']*"), r"\1<masked>"),
    (re.compile(rf"(?i)(value=[\"'])[^\"']*([\"'][^>]*?name=[\"']{_NAME}[\"'])"), r"\1<masked>\2"),
    (re.compile(r"(?i)(name=\"[^\"]*(?:token|session|csrf)[^\"]*\"\r\n\r\n)[^\r]*"), r"\1<masked>"),  # multipart parts
    (re.compile(r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "<uuid>"),
    (re.compile(r"(?<!\d)1[5-9]\d{8}(?:\d{3})?(?!\d)"), "<epoch>"),
    (re.compile(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?"), "<timestamp>"),
]


class CassetteMiss(Exception):
    """A request the cassette has no recording for."""


@dataclass
class Cassette:
    data: dict[str, Any]
    blobs: dict[str, bytes] = field(default_factory=dict)
    """Binary bodies by sha256, not yet on disk (a fresh recording)."""


def mask(value: Any) -> Any:
    """`value` with volatile strings masked, recursively."""
    if isinstance(value, str):
        for pattern, repl in MASKS:
            value = pattern.sub(repl, value)
        return value
    if isinstance(value, int | float) and not isinstance(value, bool) and (1.5e9 <= value < 2e9 or 1.5e12 <= value < 2e12):
        return "<epoch>"
    if isinstance(value, dict):
        return {k: "<masked>" if k == "_" or KEYS.fullmatch(k) else mask(v) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) == 2 and value[0] == "set-cookie":  # a header pair: keep the cookie's name only
            return ["set-cookie", re.sub(r"=.*", "=<masked>", value[1])]
        return [mask(v) for v in value]
    return value


def _request(method: str, url: str, params: Any, data: Any, json_: Any, content: bytes | None) -> dict[str, Any]:
    body = {
        k: v
        for k, v in (
            ("data", data),
            ("json", json_),
            ("content", content.decode(errors="replace") if content is not None else None),
        )
        if v is not None
    }
    # Deep-copied: a module may keep mutating the dict it passed after the call.
    return copy.deepcopy({"method": method, "url": url, "params": params or None, "body": body or None})


def _key(request: Mapping[str, Any], *, masked: bool) -> str:
    return json.dumps(mask(request) if masked else request, sort_keys=True, default=str)


class _Record(Http):
    """Wraps the real backend and notes every exchange."""

    def __init__(self, headers: Mapping[str, str], real: Callable[[], Http], cassette: Cassette) -> None:
        super().__init__(headers)
        self._real = real()
        self._cassette = cassette

    @property
    def cookies(self) -> Cookies:
        return self._real.cookies

    async def _send(self, method, url, *, params, data, json, content, headers, timeout, follow_redirects):
        r = await self._real._send(
            method, url, params=params, data=data, json=json, content=content,
            headers=headers, timeout=timeout, follow_redirects=follow_redirects,
        )
        try:
            body: dict[str, str] = {"text": r.content.decode()}
        except UnicodeDecodeError:
            digest = hashlib.sha256(r.content).hexdigest()
            self._cassette.blobs[digest] = r.content
            body = {"blob": digest}
        self._cassette.data["exchanges"].append({
            "request": _request(method, url, params, data, json, content),
            "response": {
                "status": r.status_code,
                "url": r.url,
                "encoding": r.encoding,
                "headers": [[k.lower(), v] for k, v in r.headers.multi_items() if k.lower() in KEEP_HEADERS],
                **body,
            },
        })
        return r

    async def aclose(self) -> None:
        await self._real.aclose()


class _Replay(Http):
    def __init__(self, headers: Mapping[str, str], cassette: Cassette) -> None:
        super().__init__(headers)
        self._cassette = cassette
        self._jar = httpx.Cookies()
        exchanges = cassette.data["exchanges"]
        self._raw = [_key(e["request"], masked=False) for e in exchanges]
        self._masked = [_key(e["request"], masked=True) for e in exchanges]
        self._used: set[int] = set()

    @property
    def cookies(self) -> Cookies:
        return self._jar

    def _pick(self, request: dict[str, Any]) -> int:
        raw, masked = _key(request, masked=False), _key(request, masked=True)
        for keys, key in ((self._raw, raw), (self._masked, masked)):
            for i, k in enumerate(keys):
                if k == key and i not in self._used:
                    return i
        # A request already answered (the same GET twice) gets the last answer again.
        for i in range(len(self._masked) - 1, -1, -1):
            if self._masked[i] == masked:
                return i
        raise CassetteMiss(
            f"no recorded exchange for {request['method']} {request['url']} "
            f"params={request['params']} body={request['body']}"
        )

    async def _send(self, method, url, *, params, data, json, content, headers, timeout, follow_redirects):
        i = self._pick(_request(method, url, params, data, json, content))
        self._used.add(i)
        r = self._cassette.data["exchanges"][i]["response"]
        if "blob" in r:
            body = self._cassette.blobs.get(r["blob"]) or (BLOBS / r["blob"]).read_bytes()
        else:
            body = r["text"].encode()
        headers_out = httpx.Headers([tuple(h) for h in r["headers"]])
        self._jar.extract_cookies(httpx.Response(r["status"], headers=headers_out, request=httpx.Request(method, url)))
        return Response(status_code=r["status"], url=r["url"], headers=headers_out, content=body, encoding=r["encoding"])

    async def aclose(self) -> None:
        return None


def golden(collections: list) -> list[list[str]]:
    return [[c.date.isoformat(), c.type] for c in collections]


async def replay(scraper: Scraper, cassette: Cassette) -> list[list[str]]:
    """Run the module over the cassette with today frozen; returns the golden-shaped output."""
    recorded = date.fromisoformat(cassette.data["recorded"])
    token = INTERCEPT.set(lambda headers, _real: _Replay(headers, cassette))
    try:
        # Noon UTC, so the local date is the recorded one in any timezone.
        with time_machine.travel(datetime(recorded.year, recorded.month, recorded.day, 12, tzinfo=UTC), tick=False):
            return golden(await run(scraper, cassette.data["params"]))
    finally:
        INTERCEPT.reset(token)


async def record(scraper: Scraper, params: Mapping[str, str], *, timeout: float = 60) -> Cassette:
    """Run the module live, capturing its exchanges. Raises when the run errors, is
    empty, or does not replay to the same output (so nothing bad is ever written)."""
    cassette = Cassette({"params": dict(params), "recorded": date.today().isoformat(), "exchanges": []})
    token = INTERCEPT.set(lambda headers, real: _Record(headers, real, cassette))
    try:
        result = await asyncio.wait_for(run(scraper, params), timeout)
    finally:
        INTERCEPT.reset(token)
    if not result:
        raise ValueError("empty result")
    cassette.data["golden"] = golden(result)
    if await replay(scraper, cassette) != cassette.data["golden"]:
        raise ValueError("recording does not replay to the same output")
    return cassette


def path_for(module: str, case_id: str) -> Path:
    return CASSETTES / module / (re.sub(r"[^\w.-]+", "_", case_id) + ".json")


def load(path: Path) -> Cassette:
    return Cassette(json.loads(path.read_text()))


def _comparable(data: Mapping[str, Any]) -> str:
    """What a re-recording must change to be worth a commit: the params, the golden
    output, and each exchange's method, masked URL, params and status. Bodies (request
    and response) are left out on purpose: pages carry cache-busters and random ids,
    and requests echo tokens, so they differ on every fetch."""
    return json.dumps(
        mask({
            "params": data["params"],
            "golden": data["golden"],
            "exchanges": [
                [e["request"]["method"], e["request"]["url"], e["request"]["params"], e["response"]["status"]]
                for e in data["exchanges"]
            ],
        }),
        sort_keys=True,
    )


async def still_replays(scraper: Scraper, path: Path) -> bool:
    """Whether the cassette on disk still replays to its golden output with the current module."""
    old = load(path)
    try:
        return await replay(scraper, old) == old.data["golden"]
    except Exception:  # noqa: BLE001 - a miss or a parse error both mean "stale"
        return False


def save(path: Path, cassette: Cassette, *, stale: bool = False) -> bool:
    """Write the cassette unless the file already holds an equivalent recording (see
    `_comparable`) that still replays (`stale` False). Returns whether it wrote."""
    if not stale and path.exists() and _comparable(json.loads(path.read_text())) == _comparable(cassette.data):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cassette.data, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    BLOBS.mkdir(parents=True, exist_ok=True)
    for digest, content in cassette.blobs.items():
        if not (BLOBS / digest).exists():
            (BLOBS / digest).write_bytes(content)
    return True
