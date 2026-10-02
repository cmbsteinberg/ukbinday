"""
The blob store contract, against the local directory and R2 (moto's S3 mock).

Usage:
    uv run pytest tests/test_blob_store.py -v
"""

import boto3
import pytest
from moto import mock_aws

from api.services.blob_store import BlobStoreError, LocalBlobStore, R2BlobStore

pytestmark = pytest.mark.api

BUCKET = "bins-test"


@pytest.fixture(params=["local", "r2"])
def store(request, tmp_path, monkeypatch):
    if request.param == "local":
        yield LocalBlobStore(tmp_path)
        return
    # moto only intercepts AWS hosts, so swap a mocked AWS client in for R2's
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        r2 = R2BlobStore(BUCKET, "acct", "test", "test")
        r2._s3 = s3
        yield r2


def test_get_missing_is_none(store):
    assert store.get("calendars/1.ics") is None


def test_put_then_get(store):
    store.put("calendars/1.ics", b"abc")
    assert store.get("calendars/1.ics") == b"abc"


def test_put_overwrites(store):
    store.put("calendars/1.json", b"old")
    store.put("calendars/1.json", b"new")
    assert store.get("calendars/1.json") == b"new"


def test_delete(store):
    store.put("calendars/1.ics", b"abc")
    store.delete("calendars/1.ics")
    assert store.get("calendars/1.ics") is None
    store.delete("calendars/1.ics")  # deleting a missing key is not an error


def test_keys_by_prefix(store):
    for key in ("calendars/1.ics", "calendars/1.json", "calendars/2.json", "meta/x.json"):
        store.put(key, b"x")
    assert sorted(store.keys("calendars/")) == ["calendars/1.ics", "calendars/1.json", "calendars/2.json"]
    assert list(store.keys("meta/")) == ["meta/x.json"]
    assert list(store.keys("nothing/")) == []


def test_keys_pages_through_a_large_listing(store):
    for i in range(1005):  # S3 lists 1000 per page
        store.put(f"calendars/{i}.json", b"x")
    assert len(list(store.keys("calendars/"))) == 1005


def test_local_store_writes_nothing_until_put(tmp_path):
    root = tmp_path / "data"
    store = LocalBlobStore(root)
    assert store.get("calendars/1.ics") is None
    assert list(store.keys("calendars/")) == []
    assert not root.exists()


def test_r2_client_points_at_the_account_endpoint():
    r2 = R2BlobStore(BUCKET, "acct", "key", "secret")
    assert r2._s3.meta.endpoint_url == "https://acct.r2.cloudflarestorage.com"


@pytest.fixture(params=["local", "r2"])
def broken_store(request, tmp_path, monkeypatch):
    """A store that can't be used: a file where the root directory should be, or
    a bucket that isn't there (as R2 answers once our key is revoked)."""
    if request.param == "local":
        (tmp_path / "root").write_text("not a directory")
        yield LocalBlobStore(tmp_path / "root")
        return
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        r2 = R2BlobStore(BUCKET, "acct", "test", "test")
        r2._s3 = boto3.client("s3", region_name="us-east-1")
        yield r2


def test_a_broken_store_raises_blob_store_error(broken_store):
    with pytest.raises(BlobStoreError):
        broken_store.get("calendars/1.ics")
    with pytest.raises(BlobStoreError):
        broken_store.put("calendars/1.ics", b"x")
    if isinstance(broken_store, R2BlobStore):  # a missing local dir just lists nothing
        with pytest.raises(BlobStoreError):
            list(broken_store.keys("calendars/"))
