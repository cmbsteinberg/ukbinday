"""
Drop-in async replacement for httpx.AsyncClient backed by curl_cffi.

Uses a single shared AsyncSession with a semaphore to cap concurrent
requests.  One shared curl_multi handle for all curl_cffi scrapers,
separate from the httpx clients used by other scrapers.

Usage in scrapers (applied by the patcher for flagged files):
    from api.compat.curl_cffi_fallback import AsyncClient as _CurlCffiClient
"""

from __future__ import annotations

import asyncio
from typing import Any

from curl_cffi.requests import AsyncSession

_MAX_CONCURRENT = 40
_shared: AsyncSession | None = None
_sem = asyncio.Semaphore(_MAX_CONCURRENT)


def _get_session() -> AsyncSession:
    global _shared
    if _shared is None or _shared._closed:
        _shared = AsyncSession(impersonate="chrome136", max_clients=_MAX_CONCURRENT)
    return _shared


async def close_shared_session() -> None:
    """Call on app shutdown to clean up the libcurl multi handle."""
    global _shared
    if _shared and not _shared._closed:
        await _shared.close()
        _shared = None


class Response:
    def __init__(self, resp):
        self._resp = resp
        self.status_code: int = resp.status_code
        self.headers = resp.headers
        self.text: str = resp.text
        self.content: bytes = resp.content
        self.url = resp.url
        self.encoding = resp.encoding

    def json(self, **kwargs: Any) -> Any:
        return self._resp.json(**kwargs)

    def raise_for_status(self) -> None:
        self._resp.raise_for_status()


class AsyncClient:
    def __init__(
        self,
        *,
        follow_redirects: bool = True,
        verify: Any = True,
        headers: dict[str, str] | None = None,
        timeout: float | None = 120,
        impersonate: str = "chrome136",
        **kwargs: Any,
    ):
        self._follow_redirects = follow_redirects
        self._verify = verify
        self._headers: dict[str, str] = dict(headers) if headers else {}
        self._timeout = timeout
        self._impersonate = impersonate
        self._cookies: Any = None

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    @headers.setter
    def headers(self, value: dict[str, str]) -> None:
        self._headers = dict(value)

    @property
    def cookies(self):
        if self._cookies is None:
            from http.cookiejar import CookieJar

            self._cookies = CookieJar()
        return self._cookies

    @cookies.setter
    def cookies(self, value) -> None:
        self._cookies = value

    async def get(self, url: str, **kwargs: Any) -> Response:
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Response:
        return await self._request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> Response:
        return await self._request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> Response:
        return await self._request("DELETE", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> Response:
        return await self._request("PATCH", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> Response:
        return await self._request("HEAD", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs: Any) -> Response:
        if "follow_redirects" in kwargs:
            kwargs["allow_redirects"] = kwargs.pop("follow_redirects")
        else:
            kwargs.setdefault("allow_redirects", self._follow_redirects)
        kwargs.pop("verify", None)

        merged_headers = dict(self._headers)
        if "headers" in kwargs:
            req_headers = kwargs.pop("headers")
            if req_headers:
                merged_headers.update(req_headers)
        kwargs["headers"] = merged_headers

        if self._cookies is not None and "cookies" not in kwargs:
            kwargs["cookies"] = self._cookies

        kwargs.setdefault("timeout", self._timeout)
        kwargs["verify"] = self._verify
        kwargs["impersonate"] = self._impersonate

        async with _sem:
            session = _get_session()
            resp = await session.request(method, url, **kwargs)
            return Response(resp)

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass
