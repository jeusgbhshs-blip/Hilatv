"""Private candidate previews, cached inside the authenticated project.

Callers must first establish project ownership and select the URI from a stored
candidate. This function never accepts a public download URL or a request root.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from gateway.errors import StorageError
from gateway.media_bytes import sniff_mime
from gateway.storage import read_asset_bytes
from workers.nodes.runtime import object_stores
from workers.workflow.store import project_path, project_root, valid_project_id
from workers.workflow.versions import atomic_write

MAX_PREVIEW_BYTES = 256 * 1024 * 1024
_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm", ".wav", ".mp3"}


def materialize_project_asset(
    project_id: str,
    uri: str,
    *,
    gateway: Any | None = None,
    max_bytes: int = MAX_PREVIEW_BYTES,
) -> Path | None:
    if not valid_project_id(project_id):
        return None
    project = project_path(project_id)
    expected = project_root().resolve() / project_id
    try:
        if project.is_symlink() or project.resolve() != expected:
            return None
        parsed = urlparse(uri)
        suffix = Path(unquote(parsed.path)).suffix.lower()
        if suffix not in _SUFFIXES or parsed.query or parsed.fragment:
            return None
        if parsed.scheme in {"", "file"}:
            if parsed.netloc:
                return None
            path = Path(unquote(parsed.path) if parsed.scheme else uri)
            if not path.is_absolute():
                return None
            path = path.resolve()
            if (
                path.is_relative_to(expected)
                and path.is_file()
                and path.stat().st_size <= max_bytes
            ):
                return path
            return None
        if parsed.scheme not in {"oss", "s3"}:
            return None
        folder = project / "media" / "previews"
        if not folder.resolve().is_relative_to(expected):
            return None
        target = folder / (hashlib.sha256(uri.encode("utf-8")).hexdigest() + suffix)
        if target.is_file() and not target.is_symlink() and 0 < target.stat().st_size <= max_bytes:
            return target
        if gateway is None:
            from gateway import get_gateway

            gateway = get_gateway()
        stores = object_stores(gateway)
        if not stores:
            from gateway.storage import object_store_from_env

            configured = object_store_from_env()
            stores = [configured] if configured is not None else []
        for store in stores:
            try:
                raw = read_asset_bytes(uri, store=store, max_bytes=max_bytes)
            except StorageError:
                continue
            mime = sniff_mime(raw, "")
            known = bool(mime) or raw.startswith((b"GIF87a", b"GIF89a", b"\x1aE\xdf\xa3"))
            known = known or (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
            if not known:
                return None
            atomic_write(target, raw)
            return target
    except (OSError, RuntimeError, ValueError, StorageError):
        return None
    return None
