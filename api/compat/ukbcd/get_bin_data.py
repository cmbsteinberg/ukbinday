"""Lightweight shim for uk_bin_collection.uk_bin_collection.get_bin_data.

Provides AbstractGetBinDataClass so RobBrad scrapers can define their
CouncilClass without importing the full upstream package.
"""

import logging
from abc import ABC, abstractmethod

import httpx

_LOGGER = logging.getLogger(__name__)


class AbstractGetBinDataClass(ABC):
    @abstractmethod
    def parse_data(self, page: str, **kwargs) -> dict:
        ...

    @classmethod
    def get_data(cls, url) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
            )
        }
        try:
            resp = httpx.get(url, headers=headers, verify=False, timeout=120, follow_redirects=True)
            return resp
        except httpx.HTTPError as err:
            _LOGGER.error(f"Request Error: {err}")
            raise
