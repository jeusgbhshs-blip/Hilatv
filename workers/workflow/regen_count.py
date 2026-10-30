"""Increase-only regenerate count for one project.

The number lives in ``regen_budget.json`` beside the project. It is not a
field of ``project.json`` and not a field of a version manifest. Rollback
does not open this file, so it cannot restore or lower the count.

PR #47 (T13) adds ``workers.qa.budget_store.open_project_budget`` for this
same file. ``project_regens`` and ``try_spend_regen`` are the only calls
revisions make; point those two at that module when it is on main.
"""

from __future__ import annotations

import fcntl
import json
import os

from workers.qa.settings import project_retry_cap
from workers.workflow.store import project_path

_FILE = "regen_budget.json"


def project_regens(project_id: str) -> int:
    _taken, used = _update(project_id, floor=None, spend=False)
    return used


def try_spend_regen(project_id: str) -> bool:
    """Use one regeneration if the project is still under the cap."""

    taken, _used = _update(project_id, floor=None, spend=True)
    return taken


def raise_project_regens(project_id: str, used: int) -> int:
    """Move the stored count up to ``used`` when that is higher."""

    if not isinstance(used, int) or isinstance(used, bool) or used < 0:
        raise ValueError("regen count cannot be negative")
    _taken, stored = _update(project_id, floor=used, spend=False)
    return stored


def _update(project_id: str, *, floor: int | None, spend: bool) -> tuple[bool, int]:
    path = project_path(project_id, create=True) / _FILE
    limit = project_retry_cap()
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        used = _parse(handle.read())
        if floor is not None and floor > used:
            used = floor
        taken = False
        if spend and used < limit:
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
        raise ValueError("regen budget file is unreadable") from exc
    if used < 0:
        raise ValueError("regen budget file is unreadable")
    return used
