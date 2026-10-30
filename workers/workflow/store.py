"""Project files shared by the worker, the API, and a restarted process.

Temporal holds the workflow history. This directory is the projection the
status API and WebSocket read, and the checkpoint a rerun passes back in.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from workers.workflow.contract import PIPELINE

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def valid_project_id(project_id: str) -> bool:
    return bool(_ID.fullmatch(project_id))


def project_root() -> Path:
    raw = os.getenv("HILATV_PROJECT_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(tempfile.gettempdir()) / "hilatv-projects"


def project_path(project_id: str, *, create: bool = False) -> Path:
    if not valid_project_id(project_id):
        raise ValueError("invalid project id")
    path = project_root() / project_id
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def _lock(project_id: str) -> Iterator[Path]:
    directory = project_path(project_id, create=True)
    handle = (directory / ".lock").open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield directory
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _read(directory: Path, project_id: str) -> dict[str, Any]:
    path = directory / "project.json"
    if not path.is_file():
        return {
            "project_id": project_id,
            "status": "running",
            "phase": "理解需求",
            "node": None,
            "message": "正在排队",
            "events": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _write(directory: Path, snapshot: dict[str, Any]) -> None:
    path = directory / "project.json"
    temporary = directory / ".project.json.tmp"
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def init_project(project_id: str, **fields: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "project_id": project_id,
        "status": "running",
        "phase": "理解需求",
        "node": None,
        "message": "正在排队",
        "started_at": time.time(),
        "finished_at": None,
        "elapsed_s": None,
        "deliverable": None,
        "error": None,
        "shots": [],
        "events": [],
    }
    snapshot.update(fields)
    with _lock(project_id) as directory:
        _write(directory, snapshot)
        (directory / "events.jsonl").write_text("", encoding="utf-8")
    return snapshot


def update_snapshot(project_id: str, **fields: Any) -> dict[str, Any]:
    with _lock(project_id) as directory:
        snapshot = _read(directory, project_id)
        snapshot.update(fields)
        _write(directory, snapshot)
        return snapshot


def read_snapshot(project_id: str) -> dict[str, Any] | None:
    if not valid_project_id(project_id):
        return None
    path = project_root() / project_id / "project.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def publish(project_id: str, event: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": "progress",
        "project_id": project_id,
        "node": event.get("node"),
        "phase": event.get("phase"),
        "message": event.get("message"),
        "status": event.get("status") or "running",
        "attempt": event.get("attempt"),
        "ts": time.time(),
    }
    if event.get("shot_id"):
        record["shot_id"] = event["shot_id"]
        record["shot_index"] = event.get("shot_index")
    if event.get("deliverable"):
        record["deliverable"] = event["deliverable"]
    if event.get("elapsed_s") is not None:
        record["elapsed_s"] = event["elapsed_s"]
    if event.get("error"):
        record["error"] = event["error"]
    with _lock(project_id) as directory:
        snapshot = _read(directory, project_id)
        snapshot["status"] = record["status"]
        snapshot["phase"] = record["phase"]
        snapshot["node"] = record["node"]
        snapshot["message"] = record["message"]
        if record.get("shot_id"):
            snapshot["shot_id"] = record["shot_id"]
            snapshot["shot_index"] = record.get("shot_index")
        if record.get("deliverable"):
            snapshot["deliverable"] = record["deliverable"]
        if record.get("elapsed_s") is not None:
            snapshot["elapsed_s"] = record["elapsed_s"]
        if record.get("error"):
            snapshot["error"] = record["error"]
        if record["status"] == "completed":
            snapshot["finished_at"] = record["ts"]
            snapshot["error"] = None
        summary = {
            key: record[key]
            for key in ("node", "phase", "message", "status", "shot_id", "shot_index", "ts")
            if record.get(key) is not None
        }
        events = list(snapshot.get("events") or [])
        events.append(summary)
        snapshot["events"] = events[-200:]
        with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        _write(directory, snapshot)
    return record


def read_events(project_id: str, offset: int = 0) -> list[dict[str, Any]]:
    if not valid_project_id(project_id):
        return []
    path = project_root() / project_id / "events.jsonl"
    if not path.is_file():
        return []
    found: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[max(0, offset) :]:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            break
        if isinstance(item, dict):
            found.append(item)
    return found


def save_node(project_id: str, node: str, patch: dict[str, Any]) -> None:
    if node not in PIPELINE:
        raise ValueError(f"unknown node {node}")
    with _lock(project_id) as directory:
        folder = directory / "nodes"
        folder.mkdir(exist_ok=True)
        (folder / f"{node}.json").write_text(
            json.dumps(patch, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def load_checkpoint(project_id: str) -> dict[str, Any]:
    state: dict[str, Any] = {}
    completed: list[str] = []
    folder = project_root() / project_id / "nodes"
    for node in PIPELINE:
        path = folder / f"{node}.json"
        if not path.is_file():
            continue
        patch = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(patch, dict):
            state.update(patch)
            completed.append(node)
    state["completed"] = completed
    return state
