"""Version history for one project.

Ids are server-generated. Files stay under the project directory. The index
and each manifest are written with fsync, then renamed into place, while the
project lock is held.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from workers.nodes.n18_revision.concept_gate import delivery_passes
from workers.workflow.contract import PIPELINE
from workers.workflow.store import locked_project, valid_project_id

_VERSION = re.compile(r"^[a-f0-9]{32}$")
_SHOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")


class VersionError(ValueError):
    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def list_versions(project_id: str) -> dict[str, Any]:
    if not valid_project_id(project_id):
        raise VersionError("项目不存在", status=404)
    with locked_project(project_id) as directory:
        snapshot = _snapshot(directory, project_id)
        if snapshot.get("status") == "completed" and not _index(directory)["items"]:
            _commit(
                directory,
                snapshot,
                instruction="初版",
                quality_pass=False,
                concept_degraded=False,
                executed=[],
                video_shots=[],
                decisions=[],
                shot_reviews=_unreviewed(directory),
                regen_used=int(snapshot.get("regen_used") or 0),
            )
        return _public(directory)


def restore_version(project_id: str, version_id: str) -> dict[str, Any]:
    if not valid_project_id(project_id):
        raise VersionError("项目不存在", status=404)
    _check_id(version_id)
    with locked_project(project_id) as directory:
        snapshot = _snapshot(directory, project_id)
        if snapshot.get("status") == "running":
            raise VersionError("项目仍在运行", status=409)
        manifest = _manifest(directory, version_id)
        _restore_files(directory, version_id, manifest)
        playback = _playback(directory)
        master = _inside(directory, directory / "versions" / version_id / "master.mp4")
        if master.is_file():
            _copy_bytes(master, playback)
            snapshot["deliverable"] = str(playback)
        snapshot["current_version_id"] = version_id
        concept = {"degraded": True, "ok": False} if manifest.get("concept_degraded") else None
        snapshot["quality_pass"] = delivery_passes(list(manifest.get("shots") or []), concept)
        snapshot["regen_used"] = int(manifest.get("regen_used") or 0)
        snapshot["status"] = "completed"
        snapshot["message"] = f"已回到版本 {manifest.get('index')}"
        _write_json(directory / "project.json", snapshot)
        index = _index(directory)
        index["current"] = version_id
        _write_json(directory / "versions" / "index.json", index)
        return _public(directory)


def commit_locked(
    directory: Path,
    snapshot: dict[str, Any],
    **fields: Any,
) -> dict[str, Any]:
    return _commit(directory, snapshot, **fields)


def hashes(directory: Path) -> dict[str, str]:
    folder = directory / "media"
    found: dict[str, str] = {}
    if not folder.is_dir():
        return found
    for path in sorted(folder.iterdir()):
        if not path.is_file() or not _SHOT.fullmatch(path.stem):
            continue
        found[path.stem] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def media_path(directory: Path, shot_id: str) -> Path:
    if not _SHOT.fullmatch(shot_id):
        raise VersionError("镜头编号无效")
    path = _inside(directory, directory / "media" / f"{shot_id}.bin")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_dir(path.parent)


def _commit(directory: Path, snapshot: dict[str, Any], **fields: Any) -> dict[str, Any]:
    version_id = uuid.uuid4().hex
    index = _index(directory)
    number = len(index["items"]) + 1
    folder = _inside(directory, directory / "versions" / version_id)
    folder.mkdir(parents=True, exist_ok=True)
    _copy_tree(directory / "nodes", folder / "nodes")
    _copy_tree(directory / "media", folder / "media")
    master_name = ""
    deliverable = snapshot.get("deliverable")
    if isinstance(deliverable, str) and deliverable:
        source = Path(deliverable)
        try:
            source = _inside(directory, source)
        except VersionError:
            source = Path()
        if source.is_file():
            _copy_bytes(source, folder / "master.mp4")
            master_name = "master.mp4"
    reviews = list(fields.get("shot_reviews") or [])
    concept = (
        {"degraded": True, "ok": False, "text_source": "template_fallback"}
        if fields.get("concept_degraded")
        else None
    )
    quality_pass = bool(fields.get("quality_pass")) and delivery_passes(reviews, concept)
    manifest = {
        "version_id": version_id,
        "index": number,
        "instruction": str(fields.get("instruction") or ""),
        "created_at": time.time(),
        "quality_pass": quality_pass,
        "concept_degraded": bool(fields.get("concept_degraded")),
        "executed": list(fields.get("executed") or []),
        "video_shots": list(fields.get("video_shots") or []),
        "decisions": list(fields.get("decisions") or []),
        "shots": list(fields.get("shot_reviews") or []),
        "regen_used": int(fields.get("regen_used") or 0),
        "master": master_name,
    }
    _write_json(folder / "manifest.json", manifest)
    index["items"].append(
        {
            "version_id": version_id,
            "index": number,
            "instruction": manifest["instruction"],
            "created_at": manifest["created_at"],
            "quality_pass": manifest["quality_pass"],
        }
    )
    index["current"] = version_id
    _write_json(directory / "versions" / "index.json", index)
    _fsync_dir(directory / "versions")
    return manifest


def _restore_files(directory: Path, version_id: str, manifest: dict[str, Any]) -> None:
    folder = _version_dir(directory, version_id)
    nodes = folder / "nodes"
    if nodes.is_dir():
        for path in nodes.iterdir():
            if path.suffix != ".json" or path.stem not in PIPELINE:
                continue
            _copy_bytes(path, directory / "nodes" / path.name)
    media = folder / "media"
    if media.is_dir():
        destination = directory / "media"
        destination.mkdir(parents=True, exist_ok=True)
        for path in media.iterdir():
            if path.is_file() and _SHOT.fullmatch(path.stem):
                _copy_bytes(path, media_path(directory, path.stem))
    if manifest.get("master") not in {"", "master.mp4"}:
        raise VersionError("版本清单里的成片名无效")


def _public(directory: Path) -> dict[str, Any]:
    index = _index(directory)
    current = index.get("current")
    versions = []
    for item in index["items"]:
        versions.append(
            {
                "version_id": item["version_id"],
                "index": item["index"],
                "instruction": item.get("instruction") or "",
                "created_at": item.get("created_at"),
                "quality_pass": bool(item.get("quality_pass")),
                "current": item["version_id"] == current,
            }
        )
    return {"versions": versions, "current_version_id": current}


def _manifest(directory: Path, version_id: str) -> dict[str, Any]:
    _check_id(version_id)
    index = _index(directory)
    if version_id not in {item["version_id"] for item in index["items"]}:
        raise VersionError("版本不存在", status=404)
    path = _version_dir(directory, version_id) / "manifest.json"
    if not path.is_file():
        raise VersionError("版本不存在", status=404)
    return json.loads(path.read_text(encoding="utf-8"))


def _version_dir(directory: Path, version_id: str) -> Path:
    _check_id(version_id)
    return _inside(directory, directory / "versions" / version_id)


def _check_id(version_id: str) -> None:
    if not isinstance(version_id, str) or _VERSION.fullmatch(version_id) is None:
        raise VersionError("版本不存在", status=404)


def _index(directory: Path) -> dict[str, Any]:
    path = directory / "versions" / "index.json"
    if not path.is_file():
        return {"current": None, "items": []}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not isinstance(loaded.get("items"), list):
        return {"current": None, "items": []}
    return loaded


def _snapshot(directory: Path, project_id: str) -> dict[str, Any]:
    path = directory / "project.json"
    if not path.is_file():
        raise VersionError("项目不存在", status=404)
    return json.loads(path.read_text(encoding="utf-8"))


def _unreviewed(directory: Path) -> list[dict[str, Any]]:
    reviews = []
    for shot_id in hashes(directory):
        reviews.append({"shot_id": shot_id, "visual_reviewed": False, "quality_pass": False})
    return reviews


def _playback(directory: Path) -> Path:
    return _inside(directory, directory / "playback" / "master.mp4")


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.is_file():
            _copy_bytes(path, destination / path.name)


def _copy_bytes(source: Path, destination: Path) -> None:
    atomic_write(destination, source.read_bytes())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    atomic_write(path, body)


def _inside(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise VersionError("路径超出项目目录")
    return resolved


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
