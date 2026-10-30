"""Load product and portrait bytes. Callers do not pass filesystem paths."""

from __future__ import annotations

import base64
import binascii
import os

from workers.brand_kit.store import read_asset
from workers.nodes.n01_brief.ssrf import UnsafeURL, fetch_bytes
from workers.nodes.n07_anchor.qa import QAError


def load_supplied(image_b64: str | None, uri: str | None, *, enterprise_id: str | None) -> bytes:
    if image_b64:
        return _b64(image_b64)
    if not uri:
        raise QAError("没有可读的产品图。请更换图片", retryable=False)
    if uri.startswith("brand://"):
        data = read_asset(uri, enterprise_id=enterprise_id)
        if data is None:
            raise QAError("brand uri is outside this enterprise", retryable=False)
        return data
    if uri.startswith(("http://", "https://")):
        return _fetch(uri)
    raise QAError("图片地址必须是品牌库或 http(s) 链接", retryable=False)


def load_archived(uri: str, *, enterprise_id: str | None) -> bytes | None:
    """Read one kit URI. A filesystem path on a kit is ignored."""

    if uri.startswith("brand://"):
        return read_asset(uri, enterprise_id=enterprise_id)
    if uri.startswith(("http://", "https://")):
        try:
            return _fetch(uri)
        except QAError:
            return None
    return None


def _b64(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise QAError("图片无法读取。请更换图片", retryable=False) from exc
    if not raw:
        raise QAError("图片是空的。请更换图片", retryable=False)
    return raw


def _fetch(url: str) -> bytes:
    timeout = _positive("HILATV_N1_FETCH_TIMEOUT_S", 10.0)
    max_bytes = _positive_int("HILATV_N1_FETCH_MAX_BYTES", 2_000_000)
    try:
        body, _content_type = fetch_bytes(url, timeout=timeout, max_bytes=max_bytes)
    except UnsafeURL as exc:
        raise QAError(str(exc), retryable=False) from exc
    except ValueError as exc:
        raise QAError("图片无法读取。请更换图片", retryable=False) from exc
    if not body:
        raise QAError("图片是空的。请更换图片", retryable=False)
    return body


def _positive(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
