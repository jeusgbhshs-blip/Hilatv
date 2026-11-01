"""Private media references are bounded and cannot become arbitrary file reads."""

import os
from pathlib import Path

import httpx
import pytest

from gateway.errors import StorageError
from gateway.storage import AssetRef, MemoryObjectStore, S3ObjectStore, read_asset_bytes


def test_local_media_requires_an_authorized_root(tmp_path: Path) -> None:
    own = tmp_path / "own"
    own.mkdir()
    media = own / "frame.png"
    media.write_bytes(b"image")
    assert read_asset_bytes(AssetRef(media.as_uri()), allowed_roots=[own]) == b"image"
    assert read_asset_bytes(str(media), allowed_roots=[own]) == b"image"
    other = tmp_path / "other.png"
    other.write_bytes(b"secret")
    (own / "escape.png").symlink_to(other)
    for uri in [
        str(other),
        str(own / "escape.png"),
        "file://server/etc/passwd",
        "../other.png",
        "http://127.0.0.1/a",
    ]:
        with pytest.raises(StorageError):
            read_asset_bytes(uri, allowed_roots=[own])
    with pytest.raises(StorageError):
        read_asset_bytes(str(media))
    with pytest.raises(StorageError):
        read_asset_bytes(str(media), allowed_roots=[own], max_bytes=4)


def test_object_media_accepts_both_private_schemes_and_checks_bucket() -> None:
    store = MemoryObjectStore(bucket="own")
    uri = store.put("frame.png", b"image", "image/png")
    assert read_asset_bytes(uri, store=store) == b"image"
    assert read_asset_bytes(uri.replace("oss:", "s3:"), store=store) == b"image"
    for uri in [
        "oss://other/frame.png",
        "oss://own/missing.png",
        "oss://own/frame.png?token=secret",
    ]:
        with pytest.raises(StorageError):
            read_asset_bytes(uri, store=store)
    with pytest.raises(StorageError):
        read_asset_bytes("oss://own/frame.png", store=store, max_bytes=4)


def test_local_fifo_is_rejected_without_blocking(tmp_path):
    fifo = tmp_path / "not-media.wav"
    os.mkfifo(fifo)
    with pytest.raises(StorageError):
        read_asset_bytes(str(fifo), allowed_roots=[tmp_path])


def test_s3_read_is_bounded_without_issuing_a_public_url() -> None:
    store = S3ObjectStore(
        endpoint="https://storage.example",
        access_key="test",
        secret_key="test",
        bucket="own",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"too large")),
    )
    with pytest.raises(StorageError):
        read_asset_bytes("s3://own/frame.png", store=store, max_bytes=4)
