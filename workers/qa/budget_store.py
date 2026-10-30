"""The only project regen-budget API. Other tasks must call this module.

``open_project_budget`` is the entry point. ``ProjectBudget.try_take`` and
``consume`` spend one, and nothing in this module ever lowers the count.
The value lives only in ``<project dir>/<project id>/regen_budget.json``.
The file is locked and fsynced. It is not part of a project or version
snapshot. Rolling a version back must not copy an older budget file over
this one, and must not write a smaller ``used`` through any other store.
T16 should call ``open_project_budget`` instead of keeping its own counter.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from workers.qa.settings import RetryBudget, SettingsError, project_dir, project_retry_cap


def open_project_budget(project_id: str) -> ProjectBudget:
    """Open the increase-only counter for one project. This is the shared API."""

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

    def can_take(self, count: int) -> bool:
        """True when ``count`` more regens still fit. This does not spend.

        ``try_take_n`` applies the same comparison inside the file lock.
        """

        _check_count(count)
        self.allow()
        return self.used + count <= self.limit

    def consume(self) -> None:
        self.try_take()

    def try_take(self) -> bool:
        """Spend one regen if the project still has one. False when the cap is met."""

        return self.try_take_n(1)

    def try_take_n(self, count: int) -> bool:
        """Spend ``count`` regens in one update, or spend nothing.

        The file lock makes the fit check and the add one step, the same
        rule as ``can_take``: if the whole count does not fit, nothing is
        spent. A count that already landed is never lowered. A second caller
        that arrives while this one holds the lock sees the new total, so two
        reviews cannot both spend the same remaining slots.
        """

        _check_count(count)
        taken, used = _update(self.path, limit=project_retry_cap(), take=count)
        self.used = used
        self.limit = project_retry_cap()
        return taken

    def begin_batch(self, count: int, key: str) -> str:
        """Mark one batch pending, or report why it must not run.

        Returns ``begun``, ``already``, ``pending``, or ``refused``.
        This does not change ``used``. A batch that does not fit is refused
        before anything is spent. ``already`` means this key was charged.
        ``pending`` means another caller is executing the same key.
        """

        _check_count(count)
        _check_key(key)
        status, used = _batch(
            self.path, limit=project_retry_cap(), op="begin", count=count, key=key
        )
        self.used = used
        self.limit = project_retry_cap()
        return status

    def finish_batch(self, count: int, key: str) -> bool:
        """Spend ``count`` once for ``key`` after the redo has run.

        A second finish for the same key does not add again. When the whole
        count no longer fits, nothing is spent.
        """

        _check_count(count)
        _check_key(key)
        status, used = _batch(
            self.path, limit=project_retry_cap(), op="finish", count=count, key=key
        )
        self.used = used
        self.limit = project_retry_cap()
        return status == "taken"

    def abort_batch(self, key: str) -> None:
        """Drop a pending key. The counter stays where it is."""

        _check_key(key)
        _status, used = _batch(self.path, limit=project_retry_cap(), op="abort", count=1, key=key)
        self.used = used
        self.limit = project_retry_cap()

    def batch_status(self, key: str) -> str:
        """``applied``, ``pending``, or ``free``."""

        _check_key(key)
        status, used = _batch(self.path, limit=project_retry_cap(), op="status", count=1, key=key)
        self.used = used
        self.limit = project_retry_cap()
        return status

    def _read_used(self) -> int:
        taken, used = _update(self.path, limit=project_retry_cap(), take=0)
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


def _check_count(count: int) -> None:
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise SettingsError("regen budget count must be an integer >= 1")


def _check_key(key: str) -> None:
    if not isinstance(key, str) or not key.strip() or len(key) > 200 or "\n" in key:
        raise SettingsError("regen budget key is invalid")


def _update(path: Path, *, limit: int, take: int) -> tuple[bool, int]:
    """Add ``take`` only when the whole amount still fits. Zero reads the file."""

    def change(state: dict[str, Any], cap: int) -> bool:
        if take > 0 and state["used"] + take <= cap:
            state["used"] += take
            return True
        return False

    taken, used = _with_ledger(path, limit, change)
    return bool(taken), used


def _batch(path: Path, *, limit: int, op: str, count: int, key: str) -> tuple[str, int]:
    """One locked update for a redo batch. ``used`` never goes down."""

    def change(state: dict[str, Any], cap: int) -> str:
        applied: dict[str, int] = state["applied"]
        pending: list[str] = state["pending"]
        if op == "status":
            if key in applied:
                return "applied"
            if key in pending:
                return "pending"
            return "free"
        if op == "abort":
            if key in pending:
                pending.remove(key)
            return "aborted"
        if op == "begin":
            if key in applied:
                return "already"
            if key in pending:
                return "pending"
            if state["used"] + count > cap:
                return "refused"
            pending.append(key)
            return "begun"
        if key in applied:
            return "already"
        if state["used"] + count > cap:
            if key in pending:
                pending.remove(key)
            return "refused"
        state["used"] += count
        applied[key] = count
        if key in pending:
            pending.remove(key)
        return "taken"

    status, used = _with_ledger(path, limit, change)
    return str(status), used


def _with_ledger(
    path: Path,
    limit: int,
    change: Callable[[dict[str, Any], int], Any],
) -> tuple[Any, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        state = _parse(handle.read())
        previous = state["used"]
        result = change(state, limit)
        if state["used"] < previous:
            raise SettingsError("regen budget cannot decrease")
        payload = _dump(state, limit)
        handle.seek(0)
        handle.truncate()
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        return result, state["used"]


def _parse(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {"used": 0, "applied": {}, "pending": []}
    try:
        data = json.loads(text)
        used = int(data["used"])
    except (ValueError, KeyError, TypeError) as exc:
        raise SettingsError("regen budget file is unreadable") from exc
    if used < 0:
        raise SettingsError("regen budget file is unreadable")
    applied = data.get("applied") or {}
    pending = data.get("pending") or []
    if not isinstance(applied, dict) or not isinstance(pending, list):
        raise SettingsError("regen budget file is unreadable")
    clean_applied: dict[str, int] = {}
    for key, count in applied.items():
        if not isinstance(key, str) or isinstance(count, bool) or not isinstance(count, int):
            raise SettingsError("regen budget file is unreadable")
        if count < 1:
            raise SettingsError("regen budget file is unreadable")
        clean_applied[key] = count
    clean_pending: list[str] = []
    for key in pending:
        if not isinstance(key, str):
            raise SettingsError("regen budget file is unreadable")
        clean_pending.append(key)
    return {"used": used, "applied": clean_applied, "pending": clean_pending}


def _dump(state: dict[str, Any], limit: int) -> str:
    payload: dict[str, Any] = {
        "used": state["used"],
        "limit": limit,
        "increase_only": True,
    }
    if state["applied"]:
        payload["applied"] = state["applied"]
    if state["pending"]:
        payload["pending"] = state["pending"]
    return json.dumps(payload) + "\n"
