"""素材库：按企业隔离的文件存储（本地 mock，不接对象存储）。"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from workers.assets.validation import validate_upload
from workers.identity.session import canonical_enterprise

KINDS = ("product_image", "brand_doc", "music", "font")
MAX_BYTES = 20 * 1024 * 1024
_ALLOWED = {
    "product_image": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
    "brand_doc": {".pdf", ".doc", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg"},
    "music": {".mp3", ".wav", ".m4a", ".aac", ".flac"},
    "font": {".ttf", ".otf", ".woff2"},
}
_ASSET_ID = re.compile(r"^[a-f0-9]{32}$")


def asset_root() -> Path:
    raw = os.getenv("HILATV_ASSET_DIR", "").strip()
    base = Path(raw) if raw else Path(tempfile.gettempdir()) / "hilatv-assets"
    return base


def _enterprise_dir(enterprise_id: str) -> Path:
    owner = canonical_enterprise(enterprise_id)
    if owner is None:
        raise ValueError("企业身份无效")
    root = asset_root().resolve()
    folder = root / owner
    if folder.is_symlink():
        raise ValueError("素材目录无效")
    return folder


def save_asset(enterprise_id: str, kind: str, filename: str, payload: bytes) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError("素材类型不对")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in _ALLOWED[kind]:
        raise ValueError("文件格式不支持")
    if not payload:
        raise ValueError("文件是空的")
    if len(payload) > MAX_BYTES:
        raise ValueError("文件过大")
    mime = validate_upload(filename, payload)
    asset_id = uuid.uuid4().hex
    folder = _enterprise_dir(enterprise_id) / asset_id
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"file{suffix}"
    stored.write_bytes(payload)
    meta = {
        "asset_id": asset_id,
        "kind": kind,
        "filename": Path(filename or "未命名").name[:200],
        "suffix": suffix,
        "size": len(payload),
        "mime_type": mime,
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def list_assets(enterprise_id: str, kind: str | None = None) -> list[dict[str, Any]]:
    root = _enterprise_dir(enterprise_id)
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for folder in root.iterdir():
        if folder.is_symlink() or not folder.is_dir() or not _ASSET_ID.fullmatch(folder.name):
            continue
        meta_path = folder / "meta.json"
        if meta_path.is_symlink() or not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict) or meta.get("asset_id") != folder.name:
            continue
        if kind and meta.get("kind") != kind:
            continue
        rows.append(meta)
    rows.sort(key=lambda item: item.get("asset_id", ""), reverse=True)
    return rows


def asset_file(enterprise_id: str, asset_id: str) -> Path | None:
    if not _ASSET_ID.fullmatch(asset_id):
        return None
    folder = _enterprise_dir(enterprise_id) / asset_id
    meta_path = folder / "meta.json"
    if folder.is_symlink() or meta_path.is_symlink() or not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict) or meta.get("asset_id") != asset_id:
        return None
    suffix = meta.get("suffix") or ""
    if suffix not in _ALLOWED.get(meta.get("kind"), set()):
        return None
    path = folder / f"file{suffix}"
    return path if path.is_file() and not path.is_symlink() else None


def delete_asset(enterprise_id: str, asset_id: str) -> bool:
    if not _ASSET_ID.fullmatch(asset_id):
        return False
    folder = _enterprise_dir(enterprise_id) / asset_id
    if folder.is_symlink() or not folder.is_dir():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return True
