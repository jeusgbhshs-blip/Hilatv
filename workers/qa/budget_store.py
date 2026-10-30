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
import time
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
        self.reserved = 0
        self.used = self._read_used()

    def allow(self) -> bool:
        self.limit = project_retry_cap()
        self.used = self._read_used()
        return self.used + self.reserved < self.limit

    def can_take(self, count: int) -> bool:
        """True when ``count`` more regens still fit. This does not spend.

        Pending reservations count toward the cap, the same rule as ``try_take_n``.
        """

        _check_count(count)
        self.limit = project_retry_cap()
        self.used = self._read_used()
        return self.used + self.reserved + count <= self.limit

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
        taken, used, reserved = _update(self.path, limit=project_retry_cap(), take=count)
        self.used = used
        self.reserved = reserved
        self.limit = project_retry_cap()
        return taken

    def begin_batch(self, count: int, key: str) -> str:
        """Reserve ``count`` under the ledger lock, or report why it must not run.

        Returns ``begun``, ``already``, ``pending``, or ``refused``.
        ``begun`` holds the slots until ``finish_batch`` or ``abort_batch``.
        Other takers, including ``try_take_n`` and ``can_take``, see that hold.
        ``used`` does not move here. A batch that does not fit is refused
        before anything is regenerated. ``already`` means this key was charged.
        ``pending`` means this key already holds a live reservation.
        """

        _check_count(count)
        _check_key(key)
        status, used, reserved = _batch(
            self.path, limit=project_retry_cap(), op="begin", count=count, key=key
        )
        self.used = used
        self.reserved = reserved
        self.limit = project_retry_cap()
        return status

    def finish_batch(self, count: int, key: str) -> bool:
        """Turn a reservation into ``used`` for the shots that were saved.

        ``count`` is how many shots were regenerated. Anything reserved above
        that is released. ``used`` only increases, and only by ``count``.
        A second finish for the same key does not add again. A missing
        reservation is not charged.
        """

        _check_count(count)
        _check_key(key)
        status, used, reserved = _batch(
            self.path, limit=project_retry_cap(), op="finish", count=count, key=key
        )
        self.used = used
        self.reserved = reserved
        self.limit = project_retry_cap()
        return status == "taken"

    def abort_batch(self, key: str) -> None:
        """Release a reservation. The spent counter stays where it is."""

        _check_key(key)
        _status, used, reserved = _batch(
            self.path, limit=project_retry_cap(), op="abort", count=1, key=key
        )
        self.used = used
        self.reserved = reserved
        self.limit = project_retry_cap()

    def batch_status(self, key: str) -> str:
        """``applied``, ``pending``, or ``free``. An expired reservation is ``free``."""

        _check_key(key)
        status, used, reserved = _batch(
            self.path, limit=project_retry_cap(), op="status", count=1, key=key
        )
        self.used = used
        self.reserved = reserved
        self.limit = project_retry_cap()
        return status

    def _read_used(self) -> int:
        taken, used, reserved = _update(self.path, limit=project_retry_cap(), take=0)
        del taken
        self.reserved = reserved
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


def _reserve_ttl_s() -> float:
    raw = os.getenv("HILATV_BUDGET_RESERVE_TTL_S", "").strip()
    if not raw:
        return 900.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise SettingsError("HILATV_BUDGET_RESERVE_TTL_S must be a positive number") from exc
    if value <= 0:
        raise SettingsError("HILATV_BUDGET_RESERVE_TTL_S must be a positive number")
    return value


def _reserved_total(state: dict[str, Any]) -> int:
    return sum(item["count"] for item in state["reserved"].values())


def _drop_expired(state: dict[str, Any], now: float) -> list[str]:
    expired: list[str] = []
    kept: dict[str, dict[str, float | int]] = {}
    for key, item in state["reserved"].items():
        if float(item["expires"]) <= now:
            expired.append(key)
        else:
            kept[key] = item
    state["reserved"] = kept
    return expired


def _update(path: Path, *, limit: int, take: int) -> tuple[bool, int, int]:
    """Add ``take`` only when used plus live reservations still fit. Zero reads."""

    def change(state: dict[str, Any], cap: int) -> bool:
        if take > 0 and state["used"] + _reserved_total(state) + take <= cap:
            state["used"] += take
            return True
        return False

    taken, used, reserved = _with_ledger(path, limit, change)
    return bool(taken), used, reserved


def _batch(path: Path, *, limit: int, op: str, count: int, key: str) -> tuple[str, int, int]:
    """One locked update for a redo batch. ``used`` never goes down."""

    def change(state: dict[str, Any], cap: int) -> str:
        applied: dict[str, int] = state["applied"]
        reserved: dict[str, dict[str, float | int]] = state["reserved"]
        if op == "status":
            if key in applied:
                return "applied"
            if key in reserved:
                return "pending"
            return "free"
        if op == "abort":
            reserved.pop(key, None)
            return "aborted"
        if op == "begin":
            if key in applied:
                return "already"
            if key in reserved:
                return "pending"
            if state["used"] + _reserved_total(state) + count > cap:
                return "refused"
            reserved[key] = {"count": count, "expires": time.time() + _reserve_ttl_s()}
            return "begun"
        if key in applied:
            return "already"
        reservation = reserved.get(key)
        if not isinstance(reservation, dict):
            return "refused"
        charge = count if count <= int(reservation["count"]) else int(reservation["count"])
        reserved.pop(key, None)
        if charge < 1:
            return "refused"
        state["used"] += charge
        applied[key] = charge
        return "taken"

    status, used, reserved_total = _with_ledger(path, limit, change)
    return str(status), used, reserved_total


def _with_ledger(
    path: Path,
    limit: int,
    change: Callable[[dict[str, Any], int], Any],
) -> tuple[Any, int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    expired: list[str] = []
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        state = _parse(handle.read())
        previous = state["used"]
        expired = _drop_expired(state, time.time())
        result = change(state, limit)
        if state["used"] < previous:
            raise SettingsError("regen budget cannot decrease")
        payload = _dump(state, limit)
        handle.seek(0)
        handle.truncate()
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        used = state["used"]
        reserved = _reserved_total(state)
    if expired:
        _hold_expired(path.parent.name)
    return result, used, reserved


def _hold_expired(project_id: str) -> None:
    """A crashed reservation is released. The project stops for a person."""

    from workers.workflow.store import (
        contained_file,
        read_snapshot,
        update_snapshot,
        valid_project_id,
    )

    if not valid_project_id(project_id):
        return
    snapshot = read_snapshot(project_id)
    if not isinstance(snapshot, dict):
        return
    if snapshot.get("status") == "needs_human_review" and not snapshot.get("deliverable"):
        return
    fields: dict[str, Any] = {
        "status": "needs_human_review",
        "phase": "待人工复核",
        "node": "n16_final_review",
        "message": "重生预留已超时，成片暂停，需要人工放行",
        "paused": True,
        "deliverable": None,
    }
    kept = contained_file(project_id, snapshot.get("deliverable"))
    if kept:
        fields["held_deliverable"] = kept
    update_snapshot(project_id, **fields)


def _parse(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {"used": 0, "applied": {}, "reserved": {}}
    try:
        data = json.loads(text)
        used = int(data["used"])
    except (ValueError, KeyError, TypeError) as exc:
        raise SettingsError("regen budget file is unreadable") from exc
    if used < 0:
        raise SettingsError("regen budget file is unreadable")
    applied = data.get("applied") or {}
    if not isinstance(applied, dict):
        raise SettingsError("regen budget file is unreadable")
    clean_applied: dict[str, int] = {}
    for key, count in applied.items():
        if not isinstance(key, str) or isinstance(count, bool) or not isinstance(count, int):
            raise SettingsError("regen budget file is unreadable")
        if count < 1:
            raise SettingsError("regen budget file is unreadable")
        clean_applied[key] = count
    return {"used": used, "applied": clean_applied, "reserved": _parse_reserved(data)}


def _dump(state: dict[str, Any], limit: int) -> str:
    payload: dict[str, Any] = {
        "used": state["used"],
        "limit": limit,
        "increase_only": True,
    }
    if state["applied"]:
        payload["applied"] = state["applied"]
    if state["reserved"]:
        payload["reserved"] = state["reserved"]
    return json.dumps(payload) + "\n"


def _parse_reserved(data: dict[str, Any]) -> dict[str, dict[str, float | int]]:
    raw = data.get("reserved")
    if isinstance(raw, dict):
        found: dict[str, dict[str, float | int]] = {}
        for key, item in raw.items():
            if not isinstance(key, str) or not isinstance(item, dict):
                raise SettingsError("regen budget file is unreadable")
            count = item.get("count")
            expires = item.get("expires")
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise SettingsError("regen budget file is unreadable")
            if isinstance(expires, bool) or not isinstance(expires, int | float):
                raise SettingsError("regen budget file is unreadable")
            found[key] = {"count": count, "expires": float(expires)}
        return found
    legacy = data.get("pending")
    if legacy is None:
        return {}
    if not isinstance(legacy, list):
        raise SettingsError("regen budget file is unreadable")
    # A list from the previous format has no expiry. The next touch releases it.
    found: dict[str, dict[str, float | int]] = {}
    for key in legacy:
        if not isinstance(key, str):
            raise SettingsError("regen budget file is unreadable")
        found[key] = {"count": 1, "expires": 0.0}
    return found
