"""Implicit AI label in MP4 format metadata.

《人工智能生成合成内容标识办法》第五条 requires file metadata with the content
attribute, the provider name or code, and a content id. GB 45438-2025 appendix E
(cited from the TC260 video practice guide, 2025-08) names the field ``AIGC``
and the keys Label, ContentProducer, ProduceID, ReservedCode1,
ContentPropagator, PropagateID, ReservedCode2. Label ``1`` means the file is
AI-generated synthetic content.

推断: ffmpeg ``-metadata AIGC=...`` plus ``-movflags use_metadata_tags`` is what
ffprobe reads. It is not a hand-built ``moov.udta.meta.ilst`` box. Legal should
confirm that mapping before launch. Values stay in the ASCII set appendix E
asks for, so the provider code is ``HiLatv`` rather than a Chinese company name.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

PRODUCER = "HiLatv"


def content_id(*parts: str) -> str:
    raw = "|".join(parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest[:32]


def aigc_document(*, content_id: str) -> str:
    safe = _ascii_token(content_id)
    body = {
        "Label": "1",
        "ContentProducer": PRODUCER,
        "ProduceID": safe,
        "ReservedCode1": _ascii_token(hashlib.sha256(safe.encode("utf-8")).hexdigest()[:16]),
        "ContentPropagator": PRODUCER,
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
    if not str(parsed.get("ContentProducer") or "").strip():
        raise RuntimeError("AIGC ContentProducer is empty")
    if not str(parsed.get("ProduceID") or "").strip():
        raise RuntimeError("AIGC ProduceID is empty")
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
    return token[:64] or "hilatv"
