"""Replay every committed cassette offline and compare with its golden output.

Record with `uv run python -m scripts.councils.record <module>`; see scraper_contract.md.
"""

import asyncio
import socket
from datetime import date

import pytest

from api.councils._base import Collection, Meta, Scraper
from api.councils._base.discovery import load
from scripts.councils import cassette

pytestmark = pytest.mark.api
PATHS = sorted(cassette.CASSETTES.glob("*/*.json"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("replay must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.mark.parametrize("path", PATHS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_replay_matches_golden(path):
    recorded = cassette.load(path)
    output = asyncio.run(cassette.replay(load(path.parent.name), recorded))
    assert output == recorded.data["golden"]


class _Stub(Scraper):
    meta = Meta(title="Stub", url="https://stub.example", lads=("E00000000",))
    requires = frozenset()

    async def fetch(self, address, http):
        await http.get("https://stub.example/start", params={"sid": "live-session", "_": 1791288000000})
        pdf = await http.get("https://stub.example/cal.pdf")
        return [Collection(date(2026, 10, 8), f"Bin {len(pdf.content)}")]


def _stub_cassette():
    def exchange(url, request_params, **response):
        return {
            "request": {"method": "GET", "url": url, "params": request_params, "body": None},
            "response": {"status": 200, "url": url, "encoding": "utf-8", "headers": [], **response},
        }

    return cassette.Cassette(
        {
            "params": {},
            "recorded": "2026-10-06",
            "exchanges": [
                exchange("https://stub.example/start", {"sid": "recorded-session", "_": 1700000000000}, text="ok"),
                exchange("https://stub.example/cal.pdf", None, blob="abc"),
            ],
        },
        blobs={"abc": b"\xff\xfe\x00\x01"},
    )


def test_replay_masks_volatile_params_and_reads_blobs():
    assert asyncio.run(cassette.replay(_Stub(), _stub_cassette())) == [["2026-10-08", "Bin 4"]]


def test_unrecorded_request_fails_loudly():
    recorded = _stub_cassette()
    recorded.data["exchanges"].pop(1)
    with pytest.raises(cassette.CassetteMiss):
        asyncio.run(cassette.replay(_Stub(), recorded))
