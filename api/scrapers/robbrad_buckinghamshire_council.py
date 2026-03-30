import json
from dataclasses import asdict, dataclass
from typing import Literal

import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from api.compat.ukbcd.common import check_uprn
from api.compat.ukbcd.get_bin_data import AbstractGetBinDataClass

key_hex = "F57E76482EE3DC3336495DEDEEF3962671B054FE353E815145E29C5689F72FEC"
iv_hex = "2CBF4FC35C69B82362D393A4F0B9971A"


@dataclass
class BucksInput:
    P_CLIENT_ID: Literal[152]
    P_COUNCIL_ID: Literal[34505]
    P_LANG_CODE: Literal["EN"]
    P_UPRN: str


class CouncilClass(AbstractGetBinDataClass):
    """
    Concrete classes have to implement all abstract operations of the
    base class. They can also override some operations with a default
    implementation.
    """

    def encode_body(self, bucks_input: BucksInput):
        key = bytes.fromhex(key_hex)
        iv = bytes.fromhex(iv_hex)

        json_data = json.dumps(asdict(bucks_input))
        data_bytes = json_data.encode("utf-8")

        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(data_bytes) + padder.finalize()

        backend = default_backend()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        return ciphertext.hex()

    def decode_response(self, hex_input: str):

        key = bytes.fromhex(key_hex)
        iv = bytes.fromhex(iv_hex)
        ciphertext = bytes.fromhex(hex_input)

        backend = default_backend()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
        decryptor = cipher.decryptor()
        decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()

        unpadder = padding.PKCS7(128).unpadder()
        plaintext_bytes = unpadder.update(decrypted_padded) + unpadder.finalize()
        plaintext = plaintext_bytes.decode("utf-8")

        return json.loads(plaintext)

    def parse_data(self, _: str, **kwargs) -> dict:
        try:
            user_uprn: str = kwargs.get("uprn") or ""
            check_uprn(user_uprn)
            bucks_input = BucksInput(
                P_CLIENT_ID=152, P_COUNCIL_ID=34505, P_LANG_CODE="EN", P_UPRN=user_uprn
            )

            encoded_input = self.encode_body(bucks_input)

            session = httpx.Client(follow_redirects=True)
            headers = {
                "P_PARAMETER": encoded_input,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            }
            response = session.get(
                "https://itouchvision.app/portal/itouchvision/kmbd/collectionDay",
                headers=headers,
            )

            # Check if response is successful
            if response.status_code != 200:
                raise ValueError(
                    f"API returned status code {response.status_code}: {response.text[:200]}"
                )

            output = response.text

            # Check if output looks like hex (should only contain hex characters)
            if not all(c in "0123456789ABCDEFabcdef" for c in output.strip()):
                raise ValueError(
                    f"API returned non-hex response (status {response.status_code}). Response starts with: {output[:200]}"
                )

            decoded_bins = self.decode_response(output)
            data: dict[str, list[dict[str, str]]] = {}
            data["bins"] = list(
                map(
                    lambda a: {
                        "type": a["binType"],
                        "collectionDate": a["collectionDay"].replace("-", "/"),
                    },
                    decoded_bins["collectionDay"],
                )
            )

        except Exception as e:
            # Here you can log the exception if needed
            print(f"An error occurred: {e}")
            # Optionally, re-raise the exception if you want it to propagate
            raise
        return data


# --- Adapter for Project API ---
from api.compat.hacs import Collection  # type: ignore[attr-defined]

TITLE = "Buckinghamshire"
URL = "https://www.buckinghamshire.gov.uk/waste-and-recycling/find-out-when-its-your-bin-collection/"
TEST_CASES = {}


class Source:
    def __init__(self, uprn: str | None = None):
        self.uprn = uprn
        self._scraper = BucksInput()

    async def fetch(self) -> list[Collection]:
        import asyncio
        from datetime import datetime

        kwargs = {}
        if self.uprn: kwargs['uprn'] = self.uprn

        def _run():
            page = ""
            if hasattr(self._scraper, "parse_data"):
                return self._scraper.parse_data(page, **kwargs)
            raise NotImplementedError("Could not find parse_data on scraper")

        data = await asyncio.to_thread(_run)

        entries = []
        if isinstance(data, dict) and "bins" in data:
            for item in data["bins"]:
                bin_type = item.get("type")
                date_str = item.get("collectionDate")
                if not bin_type or not date_str:
                    continue
                try:
                    if "-" in date_str:
                        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                    elif "/" in date_str:
                        dt = datetime.strptime(date_str, "%d/%m/%Y").date()
                    else:
                        continue
                    entries.append(Collection(date=dt, t=bin_type, icon=None))
                except ValueError:
                    continue
        return entries
