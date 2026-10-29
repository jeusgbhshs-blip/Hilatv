"""S3-compatible object storage over HTTP. No boto3 and no MinIO SDK.

Local MinIO and production Aliyun OSS share this client. The returned URI is
`oss://bucket/key` unless HILATV_OBJECT_URI_SCHEME=s3.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx

from gateway.errors import StorageError

_EMPTY_HASH = hashlib.sha256(b"").hexdigest()


class ObjectStore(Protocol):
    bucket: str
    scheme: str

    def put(self, key: str, data: bytes, content_type: str) -> str: ...

    def get(self, uri: str) -> bytes: ...

    def reachable(self) -> bool: ...


class MemoryObjectStore:
    """In-process store for unit tests."""

    def __init__(self, *, bucket: str = "hilatv", scheme: str = "oss") -> None:
        self.bucket = bucket
        self.scheme = scheme
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> str:
        self.objects[key] = (data, content_type)
        return self.uri(key)

    def get(self, uri: str) -> bytes:
        _scheme, bucket, key = parse_object_uri(uri)
        if bucket != self.bucket or key not in self.objects:
            raise StorageError(f"object not found: {uri}")
        return self.objects[key][0]

    def uri(self, key: str) -> str:
        return f"{self.scheme}://{self.bucket}/{key.lstrip('/')}"

    def reachable(self) -> bool:
        return True


class S3ObjectStore:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        addressing: str = "path",
        scheme: str = "oss",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region or "us-east-1"
        self.addressing = addressing if addressing in {"path", "virtual"} else "path"
        self.scheme = scheme if scheme in {"oss", "s3"} else "oss"
        self.transport = transport
        self._bucket_ready = False

    def put(self, key: str, data: bytes, content_type: str) -> str:
        self.ensure_bucket()
        response = self._signed("PUT", key, data=data, content_type=content_type)
        if response.status_code >= 400:
            raise StorageError(
                f"put {key} failed: HTTP {response.status_code} {response.text[:240]}"
            )
        return self.uri(key)

    def get(self, uri: str) -> bytes:
        _scheme, bucket, key = parse_object_uri(uri)
        if bucket != self.bucket:
            raise StorageError(f"uri bucket {bucket} does not match {self.bucket}")
        response = self._signed("GET", key, data=b"")
        if response.status_code >= 400:
            raise StorageError(
                f"get {key} failed: HTTP {response.status_code} {response.text[:240]}"
            )
        return response.content

    def ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        response = self._signed("PUT", "", data=b"", bucket_only=True)
        if response.status_code in {200, 204, 409}:
            self._bucket_ready = True
            return
        if (
            b"BucketAlreadyOwnedByYou" in response.content
            or b"BucketAlreadyExists" in response.content
        ):
            self._bucket_ready = True
            return
        raise StorageError(
            f"create bucket {self.bucket} failed: HTTP {response.status_code} {response.text[:240]}"
        )

    def reachable(self) -> bool:
        try:
            with httpx.Client(transport=self.transport, timeout=3.0) as client:
                health = client.get(f"{self.endpoint}/minio/health/live")
            if health.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        try:
            self.ensure_bucket()
        except (StorageError, httpx.HTTPError):
            return False
        return True

    def uri(self, key: str) -> str:
        return f"{self.scheme}://{self.bucket}/{key.lstrip('/')}"

    def _signed(
        self,
        method: str,
        key: str,
        *,
        data: bytes,
        content_type: str | None = None,
        bucket_only: bool = False,
    ) -> httpx.Response:
        url, canonical_uri, host = self._target(key, bucket_only=bucket_only)
        amz_date = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        payload_hash = hashlib.sha256(data).hexdigest()
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if content_type:
            headers["content-type"] = content_type
        headers["authorization"] = _authorization(
            method=method,
            canonical_uri=canonical_uri,
            headers=headers,
            payload_hash=payload_hash,
            amz_date=amz_date,
            region=self.region,
            access_key=self.access_key,
            secret_key=self.secret_key,
        )
        sent = {name: value for name, value in headers.items() if name != "host"}
        try:
            with httpx.Client(transport=self.transport, timeout=60.0) as client:
                return client.request(method, url, content=data, headers=sent)
        except httpx.HTTPError as exc:
            raise StorageError(f"{method} {url} failed") from exc

    def _target(self, key: str, *, bucket_only: bool) -> tuple[str, str, str]:
        parsed = urlparse(self.endpoint)
        if not parsed.scheme or not parsed.netloc:
            raise StorageError(f"invalid object storage endpoint: {self.endpoint}")
        clean_key = key.lstrip("/")
        if self.addressing == "virtual":
            host = f"{self.bucket}.{parsed.netloc}"
            path = "/" if bucket_only or not clean_key else "/" + _quote_key(clean_key)
            url = f"{parsed.scheme}://{host}{path}"
            return url, path, host
        host = parsed.netloc
        if bucket_only or not clean_key:
            path = "/" + _quote_key(self.bucket)
        else:
            path = "/" + _quote_key(self.bucket) + "/" + _quote_key(clean_key)
        return f"{self.endpoint}{path}", path, host


def parse_object_uri(uri: str) -> tuple[str, str, str]:
    if "://" not in uri:
        raise StorageError(f"not an object uri: {uri}")
    scheme, rest = uri.split("://", 1)
    if scheme not in {"oss", "s3"}:
        raise StorageError(f"unsupported object uri scheme: {scheme}")
    bucket, sep, key = rest.partition("/")
    if not sep or not bucket or not key:
        raise StorageError(f"object uri needs a bucket and key: {uri}")
    return scheme, bucket, key


def object_store_from_env(transport: httpx.BaseTransport | None = None) -> S3ObjectStore | None:
    endpoint = os.getenv("S3_ENDPOINT", "").strip() or os.getenv("MINIO_ENDPOINT", "").strip()
    access = os.getenv("S3_ACCESS_KEY", "").strip() or os.getenv("MINIO_ROOT_USER", "").strip()
    secret = os.getenv("S3_SECRET_KEY", "").strip() or os.getenv("MINIO_ROOT_PASSWORD", "").strip()
    bucket = os.getenv("S3_BUCKET", "").strip() or os.getenv("MINIO_BUCKET", "").strip()
    if not (endpoint and access and secret and bucket):
        return None
    region = (
        os.getenv("S3_REGION", "").strip() or os.getenv("MINIO_REGION", "").strip() or "us-east-1"
    )
    addressing = os.getenv("S3_ADDRESSING", "").strip() or "path"
    scheme = os.getenv("HILATV_OBJECT_URI_SCHEME", "").strip() or "oss"
    return S3ObjectStore(
        endpoint=endpoint,
        access_key=access,
        secret_key=secret,
        bucket=bucket,
        region=region,
        addressing=addressing,
        scheme=scheme,
        transport=transport,
    )


def _authorization(
    *,
    method: str,
    canonical_uri: str,
    headers: dict[str, str],
    payload_hash: str,
    amz_date: str,
    region: str,
    access_key: str,
    secret_key: str,
) -> str:
    signed_names = sorted(headers)
    canonical_headers = "".join(f"{name}:{headers[name].strip()}\n" for name in signed_names)
    signed_header_names = ";".join(signed_names)
    canonical = "\n".join(
        (
            method,
            canonical_uri,
            "",
            canonical_headers,
            signed_header_names,
            payload_hash,
        )
    )
    datestamp = amz_date[:8]
    scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        (
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
    )
    key = ("AWS4" + secret_key).encode("utf-8")
    for part in (datestamp, region, "s3", "aws4_request"):
        key = hmac.new(key, part.encode("utf-8"), hashlib.sha256).digest()
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        "AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_header_names}, "
        f"Signature={signature}"
    )


def _quote_key(value: str) -> str:
    return quote(value, safe="-._~/")


# Re-exported so callers can assert the empty-body hash without recomputing it.
EMPTY_PAYLOAD_HASH = _EMPTY_HASH
