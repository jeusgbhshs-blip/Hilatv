"""One exact-file release gate and owner/public media response implementation."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse

from workers.workflow.readiness import readiness
from workers.workflow.store import locked_project, project_path, read_snapshot


def public_readiness(view: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in view.items() if key != "media_path"}
    public["delivery_reasons"] = public.get("reasons") or []
    return public


def public_rights(rights: Any) -> dict[str, Any]:
    public = dict(rights) if isinstance(rights, dict) else {}
    note = public.get("materials_note")
    if isinstance(note, str) and Path(note).is_absolute():
        public["materials_note"] = Path(note).name
    return public


def media_response(
    snapshot: dict[str, Any],
    *,
    media: str | Path | None = None,
    state: dict[str, Any] | None = None,
    preview: bool = False,
    filename: str = "master.mp4",
    expected_hash: str | None = None,
    version_flags: dict[str, bool] | None = None,
) -> FileResponse:
    project_id = str(snapshot["project_id"])
    with locked_project(project_id):
        current = read_snapshot(project_id)
        if current is None or current.get("enterprise_id") != snapshot.get("enterprise_id"):
            raise HTTPException(status_code=404, detail="项目不存在")
        assessed = {
            **current,
            **{
                key: value
                for key, value in (version_flags or {}).items()
                if key in {"concept_degraded", "revision_incomplete"}
            },
        }
        view = readiness(assessed, state, media)
        if expected_hash is not None and view.get("media_hash") != expected_hash:
            raise HTTPException(status_code=410, detail="分享的文件已更新，请负责人重新创建链接")
        if not preview and view["delivery_status"] != "ready":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "delivery_not_ready",
                    "message": "当前文件尚未通过正式交付核验，请使用登录后的预览入口",
                    **public_readiness(view),
                },
            )
        if not view.get("preview_available") or not view.get("media_path"):
            raise HTTPException(status_code=404, detail="没有可播放的预览文件")
        # FileResponse opens its path later. Pin verified bytes to an immutable
        # hash-named copy so an in-place render/replace cannot change what is sent.
        pinned = _pin_media(project_id, Path(view["media_path"]), view["media_hash"])
    return FileResponse(
        pinned,
        media_type="video/mp4",
        filename=filename,
        content_disposition_type="inline" if preview else "attachment",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{view["media_hash"]}"',
            "X-HiLatv-Media-Status": str(view["delivery_status"]),
        },
    )


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pin_media(project_id: str, source: Path, digest: str) -> Path:
    root = project_path(project_id).resolve()
    folder = root / ".http-media"
    if folder.is_symlink():
        raise HTTPException(status_code=503, detail="预览存储暂不可用")
    folder.mkdir(exist_ok=True)
    dest = folder / f"{digest}.mp4"
    if dest.is_symlink():
        raise HTTPException(status_code=503, detail="预览存储暂不可用")
    if dest.is_file() and _digest(dest) == digest:
        return dest
    fd, temporary = tempfile.mkstemp(prefix=".media-", dir=folder)
    staged = Path(temporary)
    try:
        actual = hashlib.sha256()
        with os.fdopen(fd, "wb") as output, source.open("rb") as incoming:
            for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                output.write(chunk)
                actual.update(chunk)
        if actual.hexdigest() != digest:
            raise HTTPException(status_code=409, detail="媒体正在更新，请稍后重新预览")
        staged.chmod(0o400)
        os.replace(staged, dest)
        return dest
    except OSError as exc:
        raise HTTPException(status_code=503, detail="预览存储暂不可用") from exc
    finally:
        staged.unlink(missing_ok=True)
