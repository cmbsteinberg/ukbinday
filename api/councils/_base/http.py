"""HTTP for scrapers: one interface over httpx and curl_cffi, owned by the harness.

The harness opens one `Http` per lookup (so cookies never leak between
lookups), hands it to `fetch`, and closes it afterwards. Scrapers never build
clients.

Two behaviours differ from raw httpx on purpose:

- Every request checks the status by default: a 4xx/5xx raises `UpstreamError`.
  Pass `check=False` when the council signals something through the status
  (a 404 meaning "unknown UPRN") and inspect `status_code` yourself.
- Transport failures (DNS, refused, timeout, TLS) raise `UpstreamError` too,
  whichever backend is underneath.
"""

from __future__ import annotations

import json as jsonlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from typing import Any, Literal, Protocol, Self

import httpx
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException as CurlRequestException

from api.councils._base.errors import UpstreamError

Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
Params = Mapping[str, str | int | float | None]

DEFAULT_TIMEOUT = 20.0
# A pinned Chrome fingerprint (it brings its own matching headers). Not the
# floating "chrome" alias: curl_cffi 0.14 maps that to chrome142, which some
# councils' bot checks block (Swale, Eastleigh), and an upgrade would move it again.
IMPERSONATE = "chrome136"


class Transport(StrEnum):
    HTTPX = "httpx"
    CURL_CFFI = "curl_cffi"
    """TLS fingerprint impersonation, for councils behind Cloudflare/Akamai bot checks."""


class Cookies(Protocol):
    """The cookie-jar calls scrapers make; both backends' jars satisfy it."""

    def set(self, name: str, value: str, domain: str = "", path: str = "/") -> None: ...
    def get(
        self, name: str, default: str | None = None, domain: str | None = None, path: str | None = None
    ) -> str | None: ...


@dataclass(frozen=True)
class Response:
    status_code: int
    url: str
    """The final URL after redirects, always a `str`."""
    headers: httpx.Headers
    """Case-insensitive."""
    content: bytes
    encoding: str

    @cached_property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    def json(self) -> Any:
        return jsonlib.loads(self.text)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def is_redirect(self) -> bool:
        return 300 <= self.status_code < 400 and "location" in self.headers

    def raise_for_status(self) -> Self:
        if not self.ok:
            raise UpstreamError(f"HTTP {self.status_code} from {self.url}")
        return self


class Http(ABC):
    """Per-lookup HTTP session. `headers` are sent with every request and can
    be changed mid-flow (e.g. to add a bearer token once you have one)."""

    def __init__(self, headers: Mapping[str, str]) -> None:
        self.headers = httpx.Headers(headers)

    @property
    @abstractmethod
    def cookies(self) -> Cookies: ...

    async def get(
        self,
        url: str,
        *,
        params: Params | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        follow_redirects: bool = True,
        check: bool = True,
    ) -> Response:
        return await self.request(
            "GET", url, params=params, headers=headers, timeout=timeout,
            follow_redirects=follow_redirects, check=check,
        )

    async def post(
        self,
        url: str,
        *,
        params: Params | None = None,
        data: Mapping[str, Any] | None = None,
        json: Any = None,
        content: str | bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        follow_redirects: bool = True,
        check: bool = True,
    ) -> Response:
        """`data` is a form body, `json` a JSON body, `content` a raw body (SOAP, XML)."""
        return await self.request(
            "POST", url, params=params, data=data, json=json, content=content,
            headers=headers, timeout=timeout, follow_redirects=follow_redirects, check=check,
        )

    async def request(
        self,
        method: Method,
        url: str,
        *,
        params: Params | None = None,
        data: Mapping[str, Any] | None = None,
        json: Any = None,
        content: str | bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        follow_redirects: bool = True,
        check: bool = True,
    ) -> Response:
        merged = self.headers.copy()
        if headers:
            merged.update(headers)
        if isinstance(content, str):
            content = content.encode()
        response = await self._send(
            method,
            url,
            params=dict(params) if params else None,
            data=dict(data) if data is not None else None,
            json=json,
            content=content,
            # From .raw, not dict(merged): that lower-cases the names, and some
            # WAFs reject "user-agent" while accepting "User-Agent" (Boston).
            headers={k.decode(): v.decode() for k, v in merged.raw},
            timeout=DEFAULT_TIMEOUT if timeout is None else timeout,
            follow_redirects=follow_redirects,
        )
        return response.raise_for_status() if check else response

    @abstractmethod
    async def _send(
        self,
        method: Method,
        url: str,
        *,
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
        json: Any,
        content: bytes | None,
        headers: dict[str, str],
        timeout: float,
        follow_redirects: bool,
    ) -> Response: ...

    @abstractmethod
    async def aclose(self) -> None: ...


class _HttpxHttp(Http):
    def __init__(self, headers: Mapping[str, str], *, verify: bool) -> None:
        super().__init__(headers)
        self._client = httpx.AsyncClient(verify=verify)

    @property
    def cookies(self) -> Cookies:
        return self._client.cookies

    async def _send(self, method, url, *, params, data, json, content, headers, timeout, follow_redirects):
        try:
            r = await self._client.request(
                method, url, params=params, data=data, json=json, content=content,
                headers=headers, timeout=timeout, follow_redirects=follow_redirects,
            )
        except httpx.RequestError as exc:
            raise UpstreamError(f"{method} {url}: {type(exc).__name__}: {exc}") from exc
        return Response(
            status_code=r.status_code,
            url=str(r.url),
            headers=r.headers,
            content=r.content,
            encoding=r.encoding or "utf-8",
        )

    async def aclose(self) -> None:
        await self._client.aclose()


class _CurlHttp(Http):
    def __init__(self, headers: Mapping[str, str], *, verify: bool) -> None:
        super().__init__(headers)
        self._session = AsyncSession(impersonate=IMPERSONATE, verify=verify)

    @property
    def cookies(self) -> Cookies:
        return self._session.cookies

    async def _send(self, method, url, *, params, data, json, content, headers, timeout, follow_redirects):
        try:
            r = await self._session.request(
                method, url, params=params, data=content if content is not None else data,
                json=json, headers=headers, timeout=timeout, allow_redirects=follow_redirects,
            )
        except CurlRequestException as exc:
            raise UpstreamError(f"{method} {url}: {type(exc).__name__}: {exc}") from exc
        return Response(
            status_code=r.status_code,
            url=str(r.url),
            headers=httpx.Headers([(k, v) for k, v in r.headers.multi_items() if v is not None]),
            content=r.content,
            encoding=r.encoding or "utf-8",
        )

    async def aclose(self) -> None:
        await self._session.close()


@asynccontextmanager
async def open_http(
    transport: Transport, *, headers: Mapping[str, str] | None = None, verify: bool = True
) -> AsyncIterator[Http]:
    """`headers` go on every request, on top of the backend's defaults (httpx's
    own User-Agent, or curl_cffi's impersonated Chrome headers)."""
    backend = _CurlHttp if transport is Transport.CURL_CFFI else _HttpxHttp
    http: Http = backend(headers or {}, verify=verify)
    try:
        yield http
    finally:
        await http.aclose()
