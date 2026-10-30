"""Project-wide regenerate counter, stored once per project.

T12 kept this number in memory. Shots share the file, so a later shot sees
what an earlier shot already spent. The cap is ``HILATV_QA_PROJECT_RETRIES``.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from workers.qa.settings import RetryBudget, SettingsError, project_dir, project_retry_cap


def open_project_budget(project_id: str) -> ProjectBudget:
    return ProjectBudget(project_id)


def project_folder(project_id: str) -> Path:
    """Directory for one project, inside ``HILATV_PROJECT_DIR``."""

    segment = _segment(project_id)
    root = project_dir()
    folder = (root / segment).resolve()
    _inside(folder, root)
    return folder


class ProjectBudget(RetryBudget):
    """``allow`` / ``consume`` read and write the project file."""

    def __init__(self, project_id: str) -> None:
        super().__init__()
        self.project_id = _segment(project_id)
        self.path = project_folder(self.project_id) / "regen_budget.json"
        _inside(self.path, project_folder(self.project_id))
        self.used = self._read_used()

    def allow(self) -> bool:
        self.limit = project_retry_cap()
        self.used = self._read_used()
        return self.used < self.limit

    def consume(self) -> None:
        self.try_take()

    def try_take(self) -> bool:
        """Spend one regen if the project still has one. False when the cap is met."""

        taken, used = _update(self.path, limit=project_retry_cap(), take=True)
        self.used = used
        self.limit = project_retry_cap()
        return taken

    def _read_used(self) -> int:
        taken, used = _update(self.path, limit=project_retry_cap(), take=False)
        del taken
        return used


def _segment(project_id: str) -> str:
    if (
        not isinstance(project_id, str)
        or not project_id
        or project_id in {".", ".."}
        or "/" in project_id
        or "\\" in project_id
    ):
        raise SettingsError("project_id must be a single directory name")
    return project_id


def _inside(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise SettingsError("regen budget path is outside the project directory") from exc


def _update(path: Path, *, limit: int, take: bool) -> tuple[bool, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        used = _parse(handle.read())
        taken = False
        if take and used < limit:
            used += 1
            taken = True
        payload = json.dumps({"used": used, "limit": limit}) + "\n"
        handle.seek(0)
        handle.truncate()
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        return taken, used


def _parse(raw: str) -> int:
    text = raw.strip()
    if not text:
        return 0
    try:
        used = int(json.loads(text)["used"])
    except (ValueError, KeyError, TypeError) as exc:
        raise SettingsError("regen budget file is unreadable") from exc
    if used < 0:
        raise SettingsError("regen budget file is unreadable")
    return used
