"""Increase-only regeneration ledger for one project.

Manual re-runs that generate media charge this counter. The file lives beside
the project directory, never inside ``project.json``. Nothing in this module
writes a smaller ``used`` value, so restoring a snapshot cannot refund a charge.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from workers.qa.settings import project_retry_cap
from workers.workflow.store import project_root, valid_project_id


class BudgetExhausted(RuntimeError):
    """The project has no regeneration charges left."""

    def __init__(self, project_id: str, used: int, limit: int) -> None:
        self.project_id = project_id
        self.used = used
        self.limit = limit
        super().__init__(f"项目重生次数已用完（已用 {used} / 上限 {limit}），不能再重跑生成节点")


class ProjectBudget:
    """The durable counter for one project. ``charge`` only increases it."""

    def __init__(self, project_id: str, used: int, limit: int) -> None:
        self.project_id = project_id
        self.used = used
        self.limit = limit

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def charge(self, count: int = 1) -> int:
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("charge count must be an integer >= 1")
        self.used = _charge(self.project_id, count)
        self.limit = project_retry_cap()
        return self.used


def open_project_budget(project_id: str) -> ProjectBudget:
    """Load the ledger. A missing file means nothing has been charged yet."""

    if not valid_project_id(project_id):
        raise ValueError("invalid project id")
    return ProjectBudget(project_id, _read(project_id), project_retry_cap())


def ledger_path(project_id: str) -> Path:
    if not valid_project_id(project_id):
        raise ValueError("invalid project id")
    return project_root() / "_regen" / f"{project_id}.json"


def _charge(project_id: str, count: int) -> int:
    path = ledger_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            current = _read_path(path)
            limit = project_retry_cap()
            if current + count > limit:
                raise BudgetExhausted(project_id, current, limit)
            updated = current + count
            _write_at_least(path, updated, floor=current)
            return max(updated, _read_path(path))
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read(project_id: str) -> int:
    return _read_path(ledger_path(project_id))


def _read_path(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"regen ledger {path.name} is unreadable") from exc
    if not isinstance(data, dict):
        raise ValueError(f"regen ledger {path.name} is unreadable")
    used = data.get("used")
    if isinstance(used, bool) or not isinstance(used, int) or used < 0:
        raise ValueError(f"regen ledger {path.name} is unreadable")
    return used


def _write_at_least(path: Path, used: int, *, floor: int) -> None:
    """Write ``used`` only when it is not below the value already on disk."""

    current = _read_path(path)
    target = used if used >= current else current
    if target < floor:
        target = floor if floor >= current else current
    if target < current:
        return
    _replace(path, target)


def _replace(path: Path, used: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"used": used}) + "\n", encoding="utf-8")
    os.replace(temporary, path)
