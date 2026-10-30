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
from pathlib import Path

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

        Storyboard narration uses this before its two ``try_take`` calls.
        ``try_take_n`` applies the same comparison inside the file lock.
        """

        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise SettingsError("regen budget count must be an integer >= 1")
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

        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise SettingsError("regen budget count must be an integer >= 1")
        taken, used = _update(self.path, limit=project_retry_cap(), take=count)
        self.used = used
        self.limit = project_retry_cap()
        return taken

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


def _update(path: Path, *, limit: int, take: int) -> tuple[bool, int]:
    """Add ``take`` only when the whole amount still fits. Zero reads the file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        previous = _parse(handle.read())
        used = previous
        taken = False
        if take > 0 and used + take <= limit:
            used += take
            taken = True
        if used < previous:
            raise SettingsError("regen budget cannot decrease")
        payload = json.dumps({"used": used, "limit": limit, "increase_only": True}) + "\n"
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
