"""iTouchVision "collectionDay" API, used by many councils.

One GET to `api_url` with an AES-CBC encrypted `P_PARAMETER` header (the key and
IV are shared by every portal, taken from the iTouchVision JS bundle) carrying
the UPRN plus the council's client and council ids. The response is the same
encryption as a hex string, decrypting to per-service collection days.

What differs per council is data, in `ITouchVisionConfig`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from api.councils._base import Address, Collection, Http, Platform

_KEY = bytes.fromhex("F57E76482EE3DC3336495DEDEEF3962671B054FE353E815145E29C5689F72FEC")
_IV = bytes.fromhex("2CBF4FC35C69B82362D393A4F0B9971A")
DEFAULT_API_URL = "https://iweb.itouchvision.com/portal/itouchvision/kmbd/collectionDay"


@dataclass(frozen=True, slots=True, kw_only=True)
class ITouchVisionConfig:
    client_id: int
    council_id: int
    api_url: str = DEFAULT_API_URL


def encrypt(payload: dict[str, Any]) -> str:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(json.dumps(payload).encode()) + padder.finalize()
    enc = Cipher(algorithms.AES(_KEY), modes.CBC(_IV), default_backend()).encryptor()
    return (enc.update(padded) + enc.finalize()).hex()


def decrypt(hex_str: str) -> dict[str, Any]:
    dec = Cipher(algorithms.AES(_KEY), modes.CBC(_IV), default_backend()).decryptor()
    padded = dec.update(bytes.fromhex(hex_str)) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return json.loads((unpadder.update(padded) + unpadder.finalize()).decode())


class ITouchVision(Platform[ITouchVisionConfig]):
    requires = frozenset({"uprn"})

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        cfg = self.config
        payload = {
            "P_UPRN": address.need("uprn"),
            "P_CLIENT_ID": cfg.client_id,
            "P_COUNCIL_ID": cfg.council_id,
            "P_LANG_CODE": "EN",
        }
        r = await http.get(cfg.api_url, headers={"P_PARAMETER": encrypt(payload)})
        data = decrypt(r.text)

        collections = []
        for service in data["collectionDay"]:
            bin_type = service["binType"].split(" (")[0].split(":")[0]
            for key in ("collectionDay", "followingDay"):
                text = service.get(key)
                if not text:
                    continue
                try:
                    day = datetime.strptime(text, "%d-%m-%Y").date()
                except ValueError:
                    continue
                collections.append(Collection(day, bin_type))
        return collections
