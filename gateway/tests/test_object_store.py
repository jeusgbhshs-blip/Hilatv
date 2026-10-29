"""Object URI parsing and the in-memory store. Live MinIO is accept-t04."""

from __future__ import annotations

import httpx
import pytest

from gateway.errors import StorageError
from gateway.storage import MemoryObjectStore, S3ObjectStore, parse_object_uri


def test_memory_store_roundtrip_oss_uri() -> None:
    store = MemoryObjectStore()
    uri = store.put("gateway/image/a.png", b"png", "image/png")
    assert uri == "oss://hilatv/gateway/image/a.png"
    assert store.get(uri) == b"png"
    assert store.get("s3://hilatv/gateway/image/a.png") == b"png"


def test_parse_object_uri_rejects_http() -> None:
    with pytest.raises(StorageError):
        parse_object_uri("https://example.com/a.png")


def test_s3_client_uses_path_style_and_signs_the_body() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT" and request.url.path == "/hilatv":
            return httpx.Response(200)
        seen["path"] = request.url.path
        seen["auth"] = request.headers["authorization"]
        seen["hash"] = request.headers["x-amz-content-sha256"]
        seen["type"] = request.headers["content-type"]
        return httpx.Response(200)

    store = S3ObjectStore(
        endpoint="http://localhost:9000",
        access_key="hilatv",
        secret_key="hilatv_dev_secret",
        bucket="hilatv",
        transport=httpx.MockTransport(handler),
    )
    uri = store.put("gateway/image/a.png", b"png-bytes", "image/png")
    assert uri == "oss://hilatv/gateway/image/a.png"
    assert seen["path"] == "/hilatv/gateway/image/a.png"
    assert str(seen["auth"]).startswith("AWS4-HMAC-SHA256 ")
    assert "host" in str(seen["auth"])
    assert seen["type"] == "image/png"
    assert seen["hash"] != ""
