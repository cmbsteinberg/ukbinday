"""Newport: encrypt a UPRN for the collection-day API and decrypt its response."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from api.councils._base import (
    Address,
    Collection,
    Http,
    Meta,
    Scraper,
    UpstreamError,
)

_URL = "https://iweb.itouchvision.com/portal/itouchvision/kmbd/collectionDay"
_KEY_HEX = "F57E76482EE3DC3336495DEDEEF3962671B054FE353E815145E29C5689F72FEC"
_IV_HEX = "2CBF4FC35C69B82362D393A4F0B9971A"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


@dataclass
class _NewportInput:
    P_CLIENT_ID: Literal[130]
    P_COUNCIL_ID: Literal[260]
    P_LANG_CODE: Literal["EN"]
    P_UPRN: str


def _encode_body(newport_input: _NewportInput) -> str:
    key = bytes.fromhex(_KEY_HEX)
    iv = bytes.fromhex(_IV_HEX)
    data_bytes = json.dumps(asdict(newport_input)).encode("utf-8")

    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(data_bytes) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    return (encryptor.update(padded_data) + encryptor.finalize()).hex()


def _decode_response(hex_input: str) -> Any:
    key = bytes.fromhex(_KEY_HEX)
    iv = bytes.fromhex(_IV_HEX)
    ciphertext = bytes.fromhex(hex_input)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    plaintext_bytes = unpadder.update(decrypted_padded) + unpadder.finalize()
    return json.loads(plaintext_bytes.decode("utf-8"))


class Newport(Scraper):
    meta = Meta(
        title="Newport",
        url="https://www.newport.gov.uk/",
        lads=("W06000022",),
        cases={},
    )
    requires = frozenset({"uprn"})
    headers = {"User-Agent": _USER_AGENT}

    async def fetch(self, address: Address, http: Http) -> list[Collection]:
        uprn = address.need("uprn").zfill(12)
        encoded_input = _encode_body(
            _NewportInput(
                P_CLIENT_ID=130,
                P_COUNCIL_ID=260,
                P_LANG_CODE="EN",
                P_UPRN=uprn,
            )
        )

        response = await http.get(
            _URL,
            headers={"P_PARAMETER": encoded_input},
            check=False,
        )
        output = response.text

        if output.strip().startswith("<"):
            raise UpstreamError(
                f"API returned HTML error page instead of encrypted data. "
                f"Status: {response.status_code}"
            )

        try:
            decoded_bins = _decode_response(output)
            rows = decoded_bins["collectionDay"]
            collections: list[Collection] = []
            for row in rows:
                bin_type = row["binType"]
                date_str = row["collectionDay"].replace("-", "/")
                if not bin_type or not date_str:
                    continue
                try:
                    if "-" in date_str:
                        day = datetime.strptime(date_str, "%Y-%m-%d").date()
                    elif "/" in date_str:
                        day = datetime.strptime(date_str, "%d/%m/%Y").date()
                    else:
                        continue
                except ValueError:
                    continue
                collections.append(Collection(date=day, type=bin_type))
        except (KeyError, TypeError, ValueError) as exc:
            raise UpstreamError("Newport returned an invalid encrypted collection response") from exc

        return collections


SCRAPER = Newport()
