"""Implicit AI label in MP4 format metadata.

《人工智能生成合成内容标识办法》第五条 requires file metadata with the content
attribute, the provider name or code, and a content id. GB 45438-2025 appendix E
and the TC260 video practice guide (2025-08) put that JSON in ``moov.udta.meta``
under the key ``AIGC``. ffmpeg ``-metadata AIGC=...`` with ``-movflags
use_metadata_tags`` is the writer ffprobe reads. The seven fields are Label,
ContentProducer, ProduceID, ReservedCode1, ContentPropagator, PropagateID, and
ReservedCode2. Label ``1`` means the file is confirmed AI-generated.

ContentProducer is the service provider's entity code from
``HILATV_CONTENT_PRODUCER`` (待 song 确认). ProduceID is a new id on every
render. ReservedCode1 is an HMAC of the label fields. The HMAC key comes from
``HILATV_AIGC_HMAC_KEY``; mock mode uses a fixed test key and live mode refuses
to sign without a configured key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

TEST_HMAC_KEY = "hilatv-mock-hmac-not-a-secret"
PLACEHOLDER_PRODUCER = "PENDING-SONG-CONFIRM"


def content_producer() -> str:
    raw = os.getenv("HILATV_CONTENT_PRODUCER", "").strip() or PLACEHOLDER_PRODUCER
    token = _ascii_token(raw)
    if token == "HiLatv":
        raise RuntimeError("ContentProducer must be the provider code, not the product name")
    return token


def new_produce_id() -> str:
    """A new id for this render. The next render does not reuse it."""

    return uuid.uuid4().hex


def hmac_key() -> bytes:
    raw = os.getenv("HILATV_AIGC_HMAC_KEY", "").strip()
    live = os.getenv("HILATV_LIVE", "0").strip() == "1"
    if raw:
        return raw.encode("utf-8")
    if live:
        raise RuntimeError("HILATV_AIGC_HMAC_KEY is required when HILATV_LIVE=1")
    return TEST_HMAC_KEY.encode("utf-8")


def reserved_code(*, produce_id: str, producer: str) -> str:
    message = f"1|{producer}|{produce_id}|{producer}|{produce_id}".encode()
    return hmac.new(hmac_key(), message, hashlib.sha256).hexdigest()


def aigc_document(*, content_id: str) -> str:
    producer = content_producer()
    safe = _ascii_token(content_id)
    body = {
        "Label": "1",
        "ContentProducer": producer,
        "ProduceID": safe,
        "ReservedCode1": reserved_code(produce_id=safe, producer=producer),
        "ContentPropagator": producer,
        "PropagateID": safe,
        "ReservedCode2": "",
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def metadata_args(*, content_id: str) -> list[str]:
    return [
        "-movflags",
        "use_metadata_tags",
        "-metadata",
        f"AIGC={aigc_document(content_id=content_id)}",
    ]


def read_aigc(path: Path) -> dict[str, str]:
    """Return the AIGC object ffprobe stored on ``path``."""

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required")
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-print_format",
            "json",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-400:]
        raise RuntimeError(detail or "ffprobe failed")
    data = json.loads(proc.stdout.decode("utf-8"))
    tags = (data.get("format") or {}).get("tags") or {}
    raw = ""
    for key, value in tags.items():
        if str(key).lower() == "aigc" and isinstance(value, str):
            raw = value
            break
    if not raw:
        raise RuntimeError(f"{path.name} has no AIGC metadata")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("AIGC metadata is not an object")
    if str(parsed.get("Label")) != "1":
        raise RuntimeError("AIGC Label is not 1")
    if str(parsed.get("ContentProducer") or "") != content_producer():
        raise RuntimeError("AIGC ContentProducer does not match the configured provider")
    if not str(parsed.get("ProduceID") or "").strip():
        raise RuntimeError("AIGC ProduceID is empty")
    expected = reserved_code(
        produce_id=str(parsed["ProduceID"]),
        producer=str(parsed["ContentProducer"]),
    )
    if str(parsed.get("ReservedCode1") or "") != expected:
        raise RuntimeError("AIGC ReservedCode1 is not the HMAC of this render")
    return {str(key): str(value) for key, value in parsed.items()}


def _ascii_token(value: str) -> str:
    kept = []
    for char in value:
        code = ord(char)
        if char in {'"', "\\", " "}:
            continue
        if code == 0x21 or 0x23 <= code <= 0x5B or 0x5D <= code <= 0x7E:
            kept.append(char)
    token = "".join(kept)
    return token[:64] or PLACEHOLDER_PRODUCER
