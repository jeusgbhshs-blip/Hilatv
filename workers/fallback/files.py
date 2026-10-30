"""Project-local media. Remote URLs go through the SSRF guard."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path

from workers.nodes.n01_brief.ssrf import fetch_bytes
from workers.qa.pixels import resolve_project_file

_MAX_BYTES = 8_000_000


def read_bytes(uri: str) -> bytes | None:
    text = uri.strip()
    if not text or text.startswith("mock://"):
        return None
    if text.startswith(("http://", "https://")):
        try:
            data, _mime = fetch_bytes(text, timeout=5, max_bytes=_MAX_BYTES)
        except Exception:
            return None
        return data or None
    if text.startswith("data:"):
        raw = text.split(",", 1)[-1]
        try:
            return base64.b64decode(raw, validate=True)
        except binascii.Error:
            return None
    path = text[7:] if text.startswith("file://") else text
    located = resolve_project_file(Path(path))
    if not isinstance(located, Path):
        return None
    try:
        return located.read_bytes()
    except OSError:
        return None


def write_output(output: dict[str, object], dest: Path, *, kind: str) -> Path | None:
    """Write gateway bytes into ``dest`` inside the project directory."""

    encoded = output.get("mp4_b64") if kind == "video" else output.get("png_b64")
    if isinstance(encoded, str) and encoded.strip():
        try:
            data = base64.b64decode(encoded, validate=True)
        except binascii.Error:
            data = b""
        if _matches(data, kind):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return dest
    uri = output.get("uri")
    if not isinstance(uri, str):
        return None
    data = read_bytes(uri)
    if data is None or not _matches(data, kind):
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _matches(data: bytes, kind: str) -> bool:
    if kind == "video":
        return len(data) > 12 and data[4:8] == b"ftyp"
    return data.startswith(b"\x89PNG\r\n\x1a\n")
