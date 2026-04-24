"""Async iTouchVision encrypted API client.

Ported from HACS iapp_itouchvision_com.py — AES-CBC encrypted request/response
protocol used by multiple UK councils via the iTouchVision platform.
"""

import json
from datetime import datetime

import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from api.compat.hacs import Collection

_KEY = bytes.fromhex(
    "F57E76482EE3DC3336495DEDEEF3962671B054FE353E815145E29C5689F72FEC"
)
_IV = bytes.fromhex("2CBF4FC35C69B82362D393A4F0B9971A")


def _encrypt(payload: dict) -> str:
    data = json.dumps(payload).encode("utf-8")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(_KEY), modes.CBC(_IV), default_backend())
    enc = cipher.encryptor()
    return (enc.update(padded) + enc.finalize()).hex()


def _decrypt(hex_str: str) -> dict:
    ct = bytes.fromhex(hex_str)
    cipher = Cipher(algorithms.AES(_KEY), modes.CBC(_IV), default_backend())
    dec = cipher.decryptor()
    padded = dec.update(ct) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    return json.loads(plain.decode("utf-8"))


async def fetch_collections(
    uprn: str | int,
    client_id: int,
    council_id: int,
    api_url: str,
) -> list[Collection]:
    payload = {
        "P_UPRN": uprn,
        "P_CLIENT_ID": client_id,
        "P_COUNCIL_ID": council_id,
        "P_LANG_CODE": "EN",
    }

    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(
            api_url,
            headers={"P_PARAMETER": _encrypt(payload)},
        )
        response.raise_for_status()

    data = _decrypt(response.text)

    entries: list[Collection] = []
    for service in data["collectionDay"]:
        bin_type = service["binType"].split(" (")[0].split(":")[0]
        for date_key in ("collectionDay", "followingDay"):
            date_str = service.get(date_key)
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%d-%m-%Y").date()
                entries.append(Collection(date=dt, t=bin_type, icon=None))
            except ValueError:
                continue

    return entries
