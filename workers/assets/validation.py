"""Check actual uploaded bytes instead of trusting the name or client MIME.

Document/audio/font checks identify their containers; they are not malware
scanners. Images are decoded with a pixel bound before entering the library.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

_IMAGES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP", ".gif": "GIF"}
_MIMES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}
MAX_PIXELS = 36_000_000


def validate_upload(filename: str, payload: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    valid = False
    mime = "application/octet-stream"
    if suffix in _IMAGES:
        try:
            with Image.open(io.BytesIO(payload)) as image:
                if image.format != _IMAGES[suffix] or image.width * image.height > MAX_PIXELS:
                    raise ValueError("图片格式或尺寸不支持")
                image.load()
                return _MIMES[image.format]
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise ValueError("图片内容无效") from exc
    if suffix == ".pdf":
        valid, mime = payload.startswith(b"%PDF-"), "application/pdf"
    elif suffix in {".txt", ".md"}:
        try:
            payload.decode("utf-8")
            valid = b"\x00" not in payload
        except UnicodeDecodeError:
            valid = False
        mime = "text/plain"
    elif suffix == ".doc":
        valid = payload.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = set(archive.namelist())
                valid = "[Content_Types].xml" in names and "word/document.xml" in names
        except (ValueError, zipfile.BadZipFile):
            valid = False
    elif suffix == ".wav":
        valid = payload.startswith(b"RIFF") and payload[8:12] == b"WAVE"
        mime = "audio/wav"
    elif suffix == ".mp3":
        valid = payload.startswith(b"ID3") or payload[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}
        mime = "audio/mpeg"
    elif suffix == ".m4a":
        valid = payload[4:8] == b"ftyp" and payload[8:12] in {b"M4A ", b"isom", b"mp42"}
        mime = "audio/mp4"
    elif suffix == ".aac":
        valid = len(payload) > 2 and payload[0] == 255 and payload[1] & 0xF6 == 0xF0
        mime = "audio/aac"
    elif suffix == ".flac":
        valid, mime = payload.startswith(b"fLaC"), "audio/flac"
    elif suffix == ".ttf":
        valid, mime = payload[:4] in {b"\x00\x01\x00\x00", b"true"}, "font/ttf"
    elif suffix == ".otf":
        valid, mime = payload.startswith(b"OTTO"), "font/otf"
    elif suffix == ".woff2":
        valid, mime = payload.startswith(b"wOF2"), "font/woff2"
    if not valid:
        raise ValueError("文件内容与格式不匹配")
    return mime
