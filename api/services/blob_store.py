"""Minimal blob store behind the ICS cache: a local directory (dev, tests, Hetzner)
or Cloudflare R2 over the S3 API (Vercel). Sync; callers are on worker threads."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from api import config


class BlobStore(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, data: bytes) -> None: ...

    def delete(self, key: str) -> None: ...

    def keys(self, prefix: str = "") -> Iterator[str]: ...


class LocalBlobStore:
    """Keys are paths under `root`. Writes are atomic (tmp file + rename); parent
    directories are created on first put, so an unused store never touches disk."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def get(self, key: str) -> bytes | None:
        try:
            return (self.root / key).read_bytes()
        except FileNotFoundError:
            return None

    def put(self, key: str, data: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok=True)

    def keys(self, prefix: str = "") -> Iterator[str]:
        base = self.root / prefix.rpartition("/")[0]
        found = (
            p.relative_to(self.root).as_posix()
            for p in base.rglob("*")
            if p.is_file() and p.suffix != ".tmp"
        )
        yield from sorted(k for k in found if k.startswith(prefix))


class R2BlobStore:
    def __init__(
        self, bucket: str, account_id: str, access_key_id: str, secret_access_key: str
    ) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            # R2 doesn't take the default CRC checksums newer boto3 adds to every request
            config=Config(
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def get(self, key: str) -> bytes | None:
        try:
            return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self._s3.exceptions.NoSuchKey:
            return None

    def put(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=key)

    def keys(self, prefix: str = "") -> Iterator[str]:
        pages = self._s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        )
        for page in pages:
            for obj in page.get("Contents", []):
                yield obj["Key"]


def from_config() -> BlobStore:
    """R2 when `R2_BUCKET` is set, else a directory at `DATA_DIR`."""
    if config.R2_BUCKET:
        return R2BlobStore(
            config.R2_BUCKET,
            config.R2_ACCOUNT_ID,
            config.R2_ACCESS_KEY_ID,
            config.R2_SECRET_ACCESS_KEY,
        )
    return LocalBlobStore(config.DATA_DIR)
