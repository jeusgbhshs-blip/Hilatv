"""Resolve an uploaded picture without leaving the upload directory.

The id is the same one ``POST /v1/uploads`` returns. Paths are never accepted
from the client. A file owned by another enterprise is treated as missing.
"""

from __future__ import annotations

import re
from pathlib import Path

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
    folder = (root / upload_id).resolve()
    if not _inside(folder, root) or not folder.is_dir():
        raise GateError("参考图不存在", status=404)
    owner_path = folder / ".enterprise"
    stored = owner_path.read_text(encoding="utf-8").strip() if owner_path.is_file() else ""
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
    if not _inside(path, root) or not path.is_file():
        raise GateError("参考图不存在", status=404)
    if path.suffix.lower() not in _IMAGE_SUFFIX:
        raise GateError("参考图只接受图片")
    return path
