"""素材库：按企业隔离的文件存储（本地 mock，不接对象存储）。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from workers.identity.session import canonical_enterprise

KINDS = ("product_image", "brand_doc", "music", "font")
MAX_BYTES = 20 * 1024 * 1024
_ALLOWED = {
    "product_image": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
    "brand_doc": {".pdf", ".doc", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg"},
    "music": {".mp3", ".wav", ".m4a", ".aac", ".flac"},
    "font": {".ttf", ".otf", ".woff2"},
}


def asset_root() -> Path:
    raw = os.getenv("HILATV_ASSET_DIR", "").strip()
    base = Path(raw) if raw else Path(tempfile.gettempdir()) / "hilatv-assets"
    return base


def _enterprise_dir(enterprise_id: str) -> Path:
    return asset_root() / canonical_enterprise(enterprise_id)


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
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def list_assets(enterprise_id: str, kind: str | None = None) -> list[dict[str, Any]]:
    root = _enterprise_dir(enterprise_id)
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        meta_path = folder / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if kind and meta.get("kind") != kind:
            continue
        rows.append(meta)
    rows.sort(key=lambda item: item.get("asset_id", ""), reverse=True)
    return rows


def asset_file(enterprise_id: str, asset_id: str) -> Path | None:
    if not asset_id.isalnum():
        return None
    folder = _enterprise_dir(enterprise_id) / asset_id
    meta_path = folder / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    suffix = meta.get("suffix") or ""
    path = folder / f"file{suffix}"
    return path if path.is_file() else None


def delete_asset(enterprise_id: str, asset_id: str) -> bool:
    if not asset_id.isalnum():
        return False
    folder = _enterprise_dir(enterprise_id) / asset_id
    if not folder.is_dir():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return True
