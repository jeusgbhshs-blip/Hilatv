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
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from workers.workflow.contract import PIPELINE
from workers.workflow.readiness import (
    draft_context,
    evidence_for,
    invalidate_media_cache,
    readiness,
    state_from_directory,
)
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
        _recover_restore(directory)
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
        _recover_restore(directory)
        staged = _stage_restore(directory, version_id, manifest)
        playback = _playback(directory)
        if (staged / "master.mp4").is_file():
            snapshot["deliverable"] = str(playback)
        snapshot["current_version_id"] = version_id
        snapshot["concept_degraded"] = manifest.get("concept_degraded") is True
        snapshot["revision_incomplete"] = manifest.get("revision_incomplete") is True
        assessed = readiness(snapshot, state_from_directory(staged), staged / "master.mp4")
        snapshot.update(assessed)
        snapshot["preview_path"] = str(playback) if (staged / "master.mp4").is_file() else None
        snapshot["media_path"] = snapshot["preview_path"]
        # The regenerate count is not part of a version. Leave its file alone.
        snapshot.pop("regen_used", None)
        snapshot["status"] = "completed"
        snapshot["message"] = f"已回到版本 {manifest.get('index')}"
        index = _index(directory)
        index["current"] = version_id
        _swap_restore(directory, staged, snapshot, index)
        invalidate_media_cache()
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
    _write_json(folder / "canvas.json", _json_document(directory / "canvas.json"))
    _write_json(folder / "draft-context.json", draft_context(directory.name))
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
    reviewed_snapshot = {**snapshot, "concept_degraded": fields.get("concept_degraded") is True}
    assessed = readiness(reviewed_snapshot, state_from_directory(directory), folder / "master.mp4")
    quality_pass = assessed["quality_pass"]
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
        "master": master_name,
        "revision_incomplete": snapshot.get("revision_incomplete") is True,
        "delivery": assessed,
        "media_hash": assessed["media_hash"],
    }
    evidence = evidence_for(
        str(snapshot.get("project_id") or directory.name), assessed["media_hash"]
    )
    if evidence:
        _write_json(folder / "delivery-evidence.json", evidence)
    _write_json(folder / "manifest.json", manifest)
    index["items"].append(
        {
            "version_id": version_id,
            "index": number,
            "instruction": manifest["instruction"],
            "created_at": manifest["created_at"],
            "quality_pass": manifest["quality_pass"],
            "delivery_status": assessed["delivery_status"],
        }
    )
    index["current"] = version_id
    if quality_pass:
        index["last_ready"] = version_id
    _write_json(directory / "versions" / "index.json", index)
    _fsync_dir(directory / "versions")
    return manifest


def _stage_restore(directory: Path, version_id: str, manifest: dict[str, Any]) -> Path:
    """Copy the chosen version into a temp tree. The live tree is swapped later."""

    if manifest.get("master") not in {"", "master.mp4"}:
        raise VersionError("版本清单里的成片名无效")
    folder = _version_dir(directory, version_id)
    staging = directory / ".restore-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    nodes = folder / "nodes"
    if nodes.is_dir():
        destination = staging / "nodes"
        destination.mkdir()
        for path in nodes.iterdir():
            if path.suffix == ".json" and path.stem in PIPELINE:
                _copy_bytes(path, destination / path.name)
    media = folder / "media"
    if media.is_dir():
        destination = staging / "media"
        destination.mkdir()
        for path in media.iterdir():
            if path.is_file() and _SHOT.fullmatch(path.stem):
                _copy_bytes(path, destination / path.name)
    master = folder / "master.mp4"
    if master.is_file():
        _copy_bytes(master, staging / "master.mp4")
        expected_hash = manifest.get("media_hash")
        if (
            expected_hash
            and hashlib.sha256((staging / "master.mp4").read_bytes()).hexdigest() != expected_hash
        ):
            raise VersionError("版本文件与保存时的校验值不一致")
    for name in ("canvas.json", "draft-context.json"):
        source = folder / name
        if source.is_file():
            _copy_bytes(source, staging / name)
    return staging


def _swap_restore(
    directory: Path,
    staging: Path,
    snapshot: dict[str, Any],
    index: dict[str, Any],
) -> None:
    """Swap a staged tree into place. The snapshot file is the commit point.

    A crash while ``.restore-inflight`` is present puts ``.restore-prev`` back,
    including the previous snapshot, so the project is not half restored.
    """

    marker = directory / ".restore-inflight"
    marker.write_bytes(b"1")
    _fsync_dir(directory)
    previous = directory / ".restore-prev"
    if previous.exists():
        shutil.rmtree(previous)
    previous.mkdir()
    for name in ("nodes", "media"):
        live = directory / name
        staged = staging / name
        if not staged.exists():
            continue
        if live.exists():
            os.replace(live, previous / name)
        os.replace(staged, live)
    _swap_file(staging / "master.mp4", _playback(directory), previous / "master.mp4", previous)
    _swap_file(
        staging / "canvas.json", directory / "canvas.json", previous / "canvas.json", previous
    )
    atomic_write(
        staging / "project.json",
        json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
    )
    atomic_write(
        staging / "index.json",
        json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
    )
    _swap_file(
        staging / "project.json",
        directory / "project.json",
        previous / "project.json",
        previous,
    )
    index_path = directory / "versions" / "index.json"
    _swap_file(staging / "index.json", index_path, previous / "index.json", previous)
    marker.unlink(missing_ok=True)
    shutil.rmtree(previous, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)


def _swap_file(staged: Path, live: Path, backup: Path, previous: Path) -> None:
    """Replace one file from the staged tree, keeping the old bytes for recovery."""

    if not staged.is_file():
        return
    previous.mkdir(parents=True, exist_ok=True)
    if live.is_file():
        backup.parent.mkdir(parents=True, exist_ok=True)
        os.replace(live, backup)
    else:
        (previous / f"{backup.name}.missing").write_bytes(b"1")
    live.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, live)


def _recover_restore(directory: Path) -> None:
    marker = directory / ".restore-inflight"
    previous = directory / ".restore-prev"
    if not marker.exists():
        return
    for name in ("nodes", "media"):
        backup = previous / name
        live = directory / name
        if backup.exists():
            if live.exists():
                shutil.rmtree(live)
            os.replace(backup, live)
    _restore_file(previous / "master.mp4", _playback(directory), previous)
    _restore_file(previous / "canvas.json", directory / "canvas.json", previous)
    _restore_file(previous / "project.json", directory / "project.json", previous)
    _restore_file(previous / "index.json", directory / "versions" / "index.json", previous)
    marker.unlink(missing_ok=True)
    shutil.rmtree(previous, ignore_errors=True)
    staging = directory / ".restore-staging"
    if staging.exists():
        shutil.rmtree(staging)


def _restore_file(backup: Path, live: Path, previous: Path) -> None:
    if backup.is_file():
        live.parent.mkdir(parents=True, exist_ok=True)
        if live.exists():
            live.unlink()
        os.replace(backup, live)
        return
    if (previous / f"{backup.name}.missing").is_file() and live.exists():
        live.unlink()


def _public(directory: Path) -> dict[str, Any]:
    index = _index(directory)
    current = index.get("current")
    versions = []
    snapshot = _snapshot(directory, directory.name)
    for item in index["items"]:
        folder = _version_dir(directory, item["version_id"])
        manifest = _json_document(folder / "manifest.json")
        assessed = readiness(
            {
                **snapshot,
                "concept_degraded": manifest.get("concept_degraded") is True,
                "revision_incomplete": manifest.get("revision_incomplete") is True,
            },
            state_from_directory(folder),
            folder / "master.mp4",
        )
        versions.append(
            {
                "version_id": item["version_id"],
                "index": item["index"],
                "instruction": item.get("instruction") or "",
                "created_at": item.get("created_at"),
                "quality_pass": assessed["quality_pass"],
                "delivery_status": assessed["delivery_status"],
                "media_provenance": assessed["media_provenance"],
                "media_hash": assessed["media_hash"],
                "preview_available": assessed["preview_available"],
                "reasons": assessed["reasons"],
                "current": item["version_id"] == current,
            }
        )
    ready = [item["version_id"] for item in versions if item["quality_pass"]]
    return {
        "versions": versions,
        "current_version_id": current,
        "last_ready_version_id": ready[-1] if ready else None,
    }


def _json_document(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


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
