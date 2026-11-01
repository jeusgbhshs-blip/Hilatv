"""Resolve an uploaded picture without leaving the upload directory.

The id is the same one ``POST /v1/uploads`` returns. Paths are never accepted
from the client. A file owned by another enterprise is treated as missing.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from gateway.errors import StorageError
from gateway.image_inputs import MAX_IMAGE_BYTES, project_input_root
from gateway.storage import read_asset_bytes
from workers.assets.validation import validate_upload
from workers.expert.gates import GateError
from workers.identity.session import canonical_enterprise
from workers.workflow.store import project_root

_UPLOAD_ID = re.compile(r"^[a-f0-9]{32}$")
_IMAGE_SUFFIX = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})


def uploads_root() -> Path:
    root = (project_root() / "uploads").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _inside(path: Path, root: Path) -> bool:
    if ".." in path.parts or path == root:
        return False
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_upload(upload_id: str, *, enterprise_id: str) -> Path:
    """Return the one image file for this enterprise, or raise ``GateError``."""

    owner = canonical_enterprise(enterprise_id)
    if owner is None or ".." in upload_id or _UPLOAD_ID.fullmatch(upload_id) is None:
        raise GateError("参考图不存在", status=404)
    root = uploads_root()
    folder = root / upload_id
    if folder.is_symlink() or not _inside(folder.resolve(), root) or not folder.is_dir():
        raise GateError("参考图不存在", status=404)
    owner_path = folder / ".enterprise"
    stored = (
        owner_path.read_text(encoding="utf-8").strip()
        if owner_path.is_file() and not owner_path.is_symlink()
        else ""
    )
    if canonical_enterprise(stored) != owner:
        raise GateError("参考图不存在", status=404)
    found = [
        item
        for item in folder.iterdir()
        if (item.is_file() or item.is_symlink()) and not item.name.startswith(".")
    ]
    if len(found) != 1:
        raise GateError("参考图不存在", status=404)
    path = found[0].resolve()
    if found[0].is_symlink() or not _inside(path, folder.resolve()) or not path.is_file():
        raise GateError("参考图不存在", status=404)
    if path.suffix.lower() not in _IMAGE_SUFFIX:
        raise GateError("参考图只接受图片")
    return path


def materialize_reference(upload_id: str, *, enterprise_id: str, project_id: str) -> str:
    """Authorize an opaque upload, then freeze a bounded project-local copy.

    The provider can read this copy without receiving an arbitrary local root,
    a browser session token, or a publicly accessible asset URL.
    """
    path = resolve_upload(upload_id, enterprise_id=enterprise_id)
    try:
        raw = read_asset_bytes(str(path), allowed_roots=(path.parent,), max_bytes=MAX_IMAGE_BYTES)
        validate_upload(path.name, raw)
    except (StorageError, ValueError) as exc:
        raise GateError("参考图无效或超过 10 MB") from exc
    root = project_input_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    filename = hashlib.sha256(raw).hexdigest() + path.suffix.lower()
    destination = root / filename
    fd, name = tempfile.mkstemp(prefix=".reference-", dir=root)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)
    return destination.as_uri()


def materialize_attachments(
    attachments: list[dict], *, enterprise_id: str, project_id: str
) -> list[str]:
    """References for the ordinary workflow, using server-issued upload IDs."""
    raw_ids = [
        item.get("upload_id")
        for item in attachments
        if isinstance(item, dict) and item.get("kind") == "image"
    ]
    if any(not isinstance(upload_id, str) for upload_id in raw_ids):
        raise GateError("参考图不存在", status=404)
    ids = list(dict.fromkeys(raw_ids))
    if len(ids) > 14:
        raise GateError("一次最多使用 14 张参考图")
    return [
        materialize_reference(upload_id, enterprise_id=enterprise_id, project_id=project_id)
        for upload_id in ids
    ]
