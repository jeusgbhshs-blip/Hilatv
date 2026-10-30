"""The only project regen-budget API. Other tasks must call this module.

``open_project_budget`` is the entry point. ``ProjectBudget.try_take`` and
``consume`` spend one, and nothing in this module ever lowers the count.
The value lives only in ``<project dir>/<project id>/regen_budget.json``.
The file is locked and fsynced. It is not part of a project or version
snapshot. Rolling a version back must not copy an older budget file over
this one, and must not write a smaller ``used`` through any other store.
T16 should call ``open_project_budget`` instead of keeping its own counter.

Pre-live hardening (SEC-63):

* A worker records each generation with ``note_generated`` before it saves
  the shot. A reservation that expires bills those shots at expiry
  (``reconciled``), so a worker that crashed after saving is still billed.
* Every late or reconciled charge writes an audit entry with a timestamp, the
  project id, the triggering node and whether ``used`` went over the cap. It
  also emits the ``regen_budget_late_charge`` log event and holds the project.
* The audit map and ``expired_tokens`` are bounded. Old audit entries fold into
  ``audit_compacted`` totals. ``used`` itself is never touched by compaction.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from workers.logging import log_event
from workers.qa.settings import RetryBudget, SettingsError, project_dir, project_retry_cap


def open_project_budget(project_id: str, *, node: str | None = None) -> ProjectBudget:
    """Open the increase-only counter for one project. This is the shared API.

    ``node`` names the caller. It is written on reservations and audit entries.
    """

    return ProjectBudget(project_id, node=node)


def project_folder(project_id: str) -> Path:
    """Directory for one project, inside ``HILATV_PROJECT_DIR``."""

    segment = _segment(project_id)
    root = project_dir()
    folder = (root / segment).resolve()
    _inside(folder, root)
    return folder


class ProjectBudget(RetryBudget):
    """``allow`` / ``consume`` read and write the project file."""

    def __init__(self, project_id: str, *, node: str | None = None) -> None:
        super().__init__()
        self.project_id = _segment(project_id)
        self.node = node.strip() if isinstance(node, str) and node.strip() else "unknown"
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

    def begin_batch(self, count: int, key: str) -> tuple[str, str]:
        """Reserve ``count`` under the ledger lock, or report why it must not run.

        Returns ``(status, token)``. ``status`` is ``begun``, ``already``,
        ``pending``, or ``refused``. ``token`` is set only for ``begun``.
        ``finish_batch`` and ``abort_batch`` must present that token.
        ``begun`` holds the slots until finish or abort. Other takers,
        including ``try_take_n`` and ``can_take``, see that hold.
        ``used`` does not move here. A batch that does not fit is refused
        before anything is regenerated.
        """

        _check_count(count)
        _check_key(key)
        status, token, used, reserved = _batch(
            self.path,
            limit=project_retry_cap(),
            op="begin",
            count=count,
            key=key,
            token="",
            node=self.node,
        )
        self.used = used
        self.reserved = reserved
        self.limit = project_retry_cap()
        return status, token

    def finish_batch(self, count: int, key: str, token: str) -> str:
        """Bill ``count`` saved shots for this reservation token.

        Shots recorded with ``note_generated`` are billed too, even when they
        were not saved, up to the reserved count. A matching token turns that
        reservation into ``used`` and releases any unused slots. A token whose
        reservation already expired still adds ``count`` to ``used`` (up to the
        reserved count, minus what expiry already reconciled) and holds the
        project, and it does not touch a newer reservation of the same key.
        ``used`` only increases. The same token is not billed twice.
        """

        _check_count(count)
        _check_key(key)
        _check_token(token)
        status, _token, used, reserved = _batch(
            self.path, limit=project_retry_cap(), op="finish", count=count, key=key, token=token
        )
        self.used = used
        self.reserved = reserved
        self.limit = project_retry_cap()
        return status

    def note_generated(self, key: str, token: str, shot_id: str) -> str:
        """Record that N10 produced ``shot_id`` for this token, before it is saved.

        A live reservation remembers the shot, so ``finish_batch`` bills it even
        when the save never happens, and an expiry bills it if the worker
        crashed before ``finish_batch``. A token whose reservation already
        expired bills the shot right away (``audited``) and holds the project.
        Returns ``noted``, ``audited``, ``already`` or ``refused``. Never lowers
        ``used``; the same shot is not billed twice.
        """

        _check_key(key)
        _check_token(token)
        _check_key(shot_id)
        status, _token, used, reserved = _batch(
            self.path,
            limit=project_retry_cap(),
            op="note",
            count=1,
            key=key,
            token=token,
            node=self.node,
            shot_id=shot_id,
        )
        self.used = used
        self.reserved = reserved
        self.limit = project_retry_cap()
        return status

    def abort_batch(self, key: str, token: str) -> None:
        """Release this token's reservation. Another token's hold stays."""

        _check_key(key)
        _check_token(token)
        _status, _token, used, reserved = _batch(
            self.path, limit=project_retry_cap(), op="abort", count=1, key=key, token=token
        )
        self.used = used
        self.reserved = reserved
        self.limit = project_retry_cap()

    def batch_status(self, key: str) -> str:
        """``applied``, ``pending``, or ``free``. An expired reservation is ``free``."""

        _check_key(key)
        status, _token, used, reserved = _batch(
            self.path, limit=project_retry_cap(), op="status", count=1, key=key, token=""
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


def _check_token(token: str) -> None:
    if not isinstance(token, str) or not token or len(token) > 64 or "\n" in token:
        raise SettingsError("regen budget token is invalid")


def reserve_ttl_s() -> float:
    """Wall-clock lifetime of one reservation. Default 900s.

    The file is shared by processes, so the expiry has to be ``time.time``
    rather than ``time.monotonic``: another process cannot read this one's
    monotonic clock. A step of the wall clock can expire a reservation early
    or stretch it. The N16 redo loop stops on a monotonic deadline of half
    this value, so the default 900s leaves a 450s gap after the worker stops
    saving. 450s is the longest that loop will run.
    """

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


_AUDIT_MAX_DEFAULT = 200
_EXPIRED_MAX_DEFAULT = 200
_EXPIRED_RETENTION_DEFAULT_S = 7 * 24 * 3600.0


def audit_max() -> int:
    """Most audit entries kept in the ledger. Older ones fold into totals. Default 200."""

    return _positive_int("HILATV_BUDGET_AUDIT_MAX", _AUDIT_MAX_DEFAULT)


def expired_tokens_max() -> int:
    """Most expired reservation tokens remembered for a late finish. Default 200."""

    return _positive_int("HILATV_BUDGET_EXPIRED_TOKENS_MAX", _EXPIRED_MAX_DEFAULT)


def expired_retention_s() -> float:
    """How long an expired token is remembered. Default 7 days.

    Never shorter than twice the reservation TTL, so a worker that is still
    inside its own reservation window can always finish.
    """

    raw = os.getenv("HILATV_BUDGET_EXPIRED_RETENTION_S", "").strip()
    value = _EXPIRED_RETENTION_DEFAULT_S
    if raw:
        try:
            value = float(raw)
        except ValueError as exc:
            raise SettingsError(
                "HILATV_BUDGET_EXPIRED_RETENTION_S must be a positive number"
            ) from exc
        if value <= 0:
            raise SettingsError("HILATV_BUDGET_EXPIRED_RETENTION_S must be a positive number")
    return max(value, 2 * reserve_ttl_s())


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise SettingsError(f"{name} must be a positive integer")
    return value


def _reserved_total(state: dict[str, Any]) -> int:
    return sum(item["count"] for item in state["reserved"].values())


def _drop_expired(state: dict[str, Any], now: float, ctx: dict[str, Any]) -> list[str]:
    """Move expired holds aside and bill the shots their worker already produced.

    ``now`` is wall-clock seconds, matching the expiry stored in the file. A
    worker records each generation before it saves, so a worker that crashed
    after saving (and never called ``finish_batch``) is billed here. A late
    finish can still top up to what it saved, never past the reserved count.
    """

    expired: list[str] = []
    kept: dict[str, dict[str, Any]] = {}
    remembered = state["expired_tokens"]
    for key, item in state["reserved"].items():
        if float(item["expires"]) <= now:
            expired.append(key)
            token = str(item.get("token") or "")
            if token and token not in state["audit"]:
                count = int(item["count"])
                generated = list(item.get("generated") or [])[:count]
                remembered[token] = {
                    "count": count,
                    "key": key,
                    "node": str(item.get("node") or "unknown"),
                    "expired_at": now,
                    "billed": 0,
                    "generated": generated,
                }
                if generated:
                    _bill_stale(state, token, len(generated), reason="reconciled", ctx=ctx)
        else:
            kept[key] = item
    state["reserved"] = kept
    return expired


def _bill_stale(
    state: dict[str, Any], token: str, target: int, *, reason: str, ctx: dict[str, Any]
) -> bool:
    """Raise this expired token's billing to ``target`` shots. True when ``used`` moved.

    This is the only path that may push ``used`` past the cap: the shots were
    really generated, so they are recorded rather than dropped. Each charge
    writes an audit entry, emits ``regen_budget_late_charge`` and holds the
    project.
    """

    entry = state["expired_tokens"][token]
    ceiling = int(entry["count"])
    billed = int(entry.get("billed") or 0)
    goal = min(target, ceiling)
    extra = goal - billed
    if extra < 1:
        return False
    before = int(state["used"])
    state["used"] = before + extra
    entry["billed"] = goal
    cap = int(ctx["cap"])
    row = {
        "count": goal,
        "key": str(entry.get("key") or ""),
        "reason": reason,
        "at": float(ctx["now"]),
        "project_id": str(ctx["project_id"]),
        "node": str(entry.get("node") or "unknown"),
        "used_before": before,
        "used_after": int(state["used"]),
        "cap": cap,
        "over_cap": int(state["used"]) > cap,
    }
    state["audit"][token] = row
    ctx["hold"] = True
    ctx["events"].append(
        {
            "event": "regen_budget_late_charge",
            "project_id": row["project_id"],
            "node": row["node"],
            "reason": reason,
            "key": row["key"],
            "charged": extra,
            "used_before": before,
            "used_after": row["used_after"],
            "cap": cap,
            "over_cap": row["over_cap"],
            "at": row["at"],
        }
    )
    return True


def _compact(state: dict[str, Any], now: float, ctx: dict[str, Any]) -> None:
    """Bound ``expired_tokens`` and ``audit``. ``used`` is never touched here."""

    remembered: dict[str, dict[str, Any]] = state["expired_tokens"]
    for entry in remembered.values():
        entry.setdefault("expired_at", now)
    horizon = now - expired_retention_s()
    dropped = [
        token for token, entry in remembered.items() if float(entry["expired_at"]) <= horizon
    ]
    limit = expired_tokens_max()
    live = [token for token in remembered if token not in dropped]
    if len(live) > limit:
        live.sort(key=lambda token: float(remembered[token]["expired_at"]))
        dropped.extend(live[: len(live) - limit])
    for token in dropped:
        entry = remembered.pop(token)
        ctx["events"].append(
            {
                "event": "regen_budget_expired_token_dropped",
                "project_id": str(ctx["project_id"]),
                "node": str(entry.get("node") or "unknown"),
                "key": str(entry.get("key") or ""),
                "billed": int(entry.get("billed") or 0),
            }
        )

    audit: dict[str, dict[str, Any]] = state["audit"]
    cap = audit_max()
    if len(audit) <= cap:
        return
    # Never fold an entry whose expired token can still be topped up.
    order = sorted(
        (token for token in audit if token not in remembered),
        key=lambda token: float(audit[token].get("at") or 0.0),
    )
    excess = len(audit) - cap
    folded = state["audit_compacted"]
    for token in order[:excess]:
        row = audit.pop(token)
        folded["entries"] = int(folded.get("entries") or 0) + 1
        folded["count"] = int(folded.get("count") or 0) + int(row["count"])
        if row.get("reason") in {"late", "reconciled"}:
            folded["late"] = int(folded.get("late") or 0) + 1
        if row.get("over_cap") is True:
            folded["over_cap"] = int(folded.get("over_cap") or 0) + 1
        folded["through"] = max(float(folded.get("through") or 0.0), float(row.get("at") or 0.0))


def _update(path: Path, *, limit: int, take: int) -> tuple[bool, int, int]:
    """Add ``take`` only when used plus live reservations still fit. Zero reads."""

    def change(state: dict[str, Any], cap: int, ctx: dict[str, Any]) -> bool:
        del ctx
        if take > 0 and state["used"] + _reserved_total(state) + take <= cap:
            state["used"] += take
            return True
        return False

    taken, used, reserved = _with_ledger(path, limit, change)
    return bool(taken), used, reserved


def _batch(
    path: Path,
    *,
    limit: int,
    op: str,
    count: int,
    key: str,
    token: str,
    node: str = "unknown",
    shot_id: str = "",
) -> tuple[str, str, int, int]:
    """One locked update for a redo batch. ``used`` never goes down."""

    def change(state: dict[str, Any], cap: int, ctx: dict[str, Any]) -> tuple[str, str]:
        return _change_batch(
            state,
            cap=cap,
            op=op,
            count=count,
            key=key,
            token=token,
            node=node,
            shot_id=shot_id,
            ctx=ctx,
        )

    result, used, reserved_total = _with_ledger(path, limit, change)
    status, issued = result
    return str(status), str(issued), used, reserved_total


def _change_batch(
    state: dict[str, Any],
    *,
    cap: int,
    op: str,
    count: int,
    key: str,
    token: str,
    node: str,
    shot_id: str,
    ctx: dict[str, Any],
) -> tuple[str, str]:
    applied: dict[str, int] = state["applied"]
    reserved: dict[str, dict[str, Any]] = state["reserved"]
    audit: dict[str, dict[str, Any]] = state["audit"]
    remembered: dict[str, dict[str, Any]] = state["expired_tokens"]
    if op == "status":
        if key in applied:
            return "applied", ""
        if key in reserved:
            return "pending", ""
        return "free", ""
    if op == "abort":
        reservation = reserved.get(key)
        if isinstance(reservation, dict) and reservation.get("token") == token:
            reserved.pop(key, None)
        return "aborted", ""
    if op == "begin":
        if key in applied:
            return "already", ""
        if key in reserved:
            return "pending", ""
        if state["used"] + _reserved_total(state) + count > cap:
            return "refused", ""
        issued = uuid.uuid4().hex
        reserved[key] = {
            "count": count,
            "expires": time.time() + reserve_ttl_s(),
            "token": issued,
            "node": node,
            "at": float(ctx["now"]),
            "generated": [],
        }
        return "begun", issued
    reservation = reserved.get(key)
    matched = isinstance(reservation, dict) and reservation.get("token") == token
    if op == "note":
        if matched:
            generated = reservation.setdefault("generated", [])
            if shot_id not in generated and len(generated) < int(reservation["count"]):
                generated.append(shot_id)
            return "noted", ""
        stale = remembered.get(token)
        if isinstance(stale, dict):
            generated = stale.setdefault("generated", [])
            if shot_id not in generated and len(generated) < int(stale["count"]):
                generated.append(shot_id)
            charged = _bill_stale(state, token, len(generated), reason="late", ctx=ctx)
            return ("audited" if charged else "already"), ""
        if token in audit:
            return "already", ""
        return "refused", ""
    # op == "finish"
    if token in audit and token not in remembered:
        return "already", ""
    if matched:
        ceiling = int(reservation["count"])
        wanted = max(count, len(reservation.get("generated") or []))
        charge = wanted if wanted <= ceiling else ceiling
        reserved.pop(key, None)
        if charge < 1:
            return "refused", ""
        before = int(state["used"])
        state["used"] += charge
        applied[key] = charge
        audit[token] = {
            "count": charge,
            "key": key,
            "reason": "finished",
            "at": float(ctx["now"]),
            "project_id": str(ctx["project_id"]),
            "node": str(reservation.get("node") or node),
            "used_before": before,
            "used_after": int(state["used"]),
            "cap": cap,
            "over_cap": int(state["used"]) > cap,
        }
        return "taken", ""
    stale = remembered.get(token)
    if not isinstance(stale, dict):
        return "refused", ""
    target = max(count, len(stale.get("generated") or []))
    charged = _bill_stale(state, token, target, reason="late", ctx=ctx)
    billed = int(stale.get("billed") or 0)
    # The worker has finished. Its token is not kept for another top-up.
    remembered.pop(token, None)
    if charged:
        return "audited", ""
    if billed > 0:
        return "already", ""
    return "refused", ""


def _with_ledger(
    path: Path,
    limit: int,
    change: Callable[[dict[str, Any], int, dict[str, Any]], Any],
) -> tuple[Any, int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    expired: list[str] = []
    now = time.time()
    ctx: dict[str, Any] = {
        "now": now,
        "cap": limit,
        "project_id": path.parent.name,
        "events": [],
        "hold": False,
    }
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        state = _parse(handle.read())
        previous = state["used"]
        expired = _drop_expired(state, now, ctx)
        result = change(state, limit, ctx)
        _compact(state, now, ctx)
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
    # Log and hold only after the ledger lock is released. See hold_expired_budget.
    for event in ctx["events"]:
        fields = dict(event)
        name = str(fields.pop("event"))
        project_id = fields.pop("project_id", None)
        node = fields.pop("node", None)
        log_event(name, project_id=project_id, node=node, **fields)
    if expired or ctx["hold"]:
        from workers.workflow.store import hold_expired_budget

        hold_expired_budget(path.parent.name)
    return result, used, reserved


def _empty() -> dict[str, Any]:
    return {
        "used": 0,
        "applied": {},
        "reserved": {},
        "expired_tokens": {},
        "audit": {},
        "audit_compacted": {},
    }


def _parse(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return _empty()
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
    return {
        "used": used,
        "applied": clean_applied,
        "reserved": _parse_reserved(data),
        "expired_tokens": _parse_token_map(data.get("expired_tokens")),
        "audit": _parse_token_map(data.get("audit"), with_reason=True),
        "audit_compacted": _parse_compacted(data.get("audit_compacted")),
    }


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
    if state["expired_tokens"]:
        payload["expired_tokens"] = state["expired_tokens"]
    if state["audit"]:
        payload["audit"] = state["audit"]
    if state["audit_compacted"]:
        payload["audit_compacted"] = state["audit_compacted"]
    return json.dumps(payload) + "\n"


def _parse_reserved(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = data.get("reserved")
    if isinstance(raw, dict):
        found: dict[str, dict[str, Any]] = {}
        for key, item in raw.items():
            if not isinstance(key, str) or not isinstance(item, dict):
                raise SettingsError("regen budget file is unreadable")
            count = item.get("count")
            expires = item.get("expires")
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise SettingsError("regen budget file is unreadable")
            if isinstance(expires, bool) or not isinstance(expires, int | float):
                raise SettingsError("regen budget file is unreadable")
            token = item.get("token")
            node = item.get("node")
            at = item.get("at")
            started = float(at) if isinstance(at, int | float) and not isinstance(at, bool) else 0.0
            row: dict[str, Any] = {
                "count": count,
                "expires": float(expires),
                "token": token,
                "node": node if isinstance(node, str) and node else "unknown",
                "at": started,
                "generated": _shot_list(item.get("generated")),
            }
            if not isinstance(token, str) or not token:
                row["expires"] = 0.0
                row["token"] = ""
            found[key] = row
        return found
    legacy = data.get("pending")
    if legacy is None:
        return {}
    if not isinstance(legacy, list):
        raise SettingsError("regen budget file is unreadable")
    # A list from the previous format has no expiry. The next touch releases it.
    found = {}
    for key in legacy:
        if not isinstance(key, str):
            raise SettingsError("regen budget file is unreadable")
        found[key] = {
            "count": 1,
            "expires": 0.0,
            "token": "",
            "node": "unknown",
            "at": 0.0,
            "generated": [],
        }
    return found


def _shot_list(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise SettingsError("regen budget file is unreadable")
    return list(dict.fromkeys(raw))


_EXTRA_NUMBERS = ("at", "expired_at")
_EXTRA_INTS = ("billed", "used_before", "used_after", "cap")
_EXTRA_TEXT = ("node", "project_id")


def _parse_token_map(raw: object, *, with_reason: bool = False) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SettingsError("regen budget file is unreadable")
    found: dict[str, dict[str, Any]] = {}
    for token, item in raw.items():
        if not isinstance(token, str) or not isinstance(item, dict):
            raise SettingsError("regen budget file is unreadable")
        count = item.get("count")
        key = item.get("key")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise SettingsError("regen budget file is unreadable")
        if not isinstance(key, str):
            raise SettingsError("regen budget file is unreadable")
        row: dict[str, Any] = {"count": count, "key": key}
        if with_reason:
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason:
                raise SettingsError("regen budget file is unreadable")
            row["reason"] = reason
        for name in _EXTRA_NUMBERS:
            value = item.get(name)
            if isinstance(value, int | float) and not isinstance(value, bool):
                row[name] = float(value)
        for name in _EXTRA_INTS:
            value = item.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                row[name] = value
        for name in _EXTRA_TEXT:
            value = item.get(name)
            if isinstance(value, str) and value:
                row[name] = value
        if isinstance(item.get("over_cap"), bool):
            row["over_cap"] = item["over_cap"]
        if "generated" in item:
            row["generated"] = _shot_list(item.get("generated"))
        found[token] = row
    return found


def _parse_compacted(raw: object) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SettingsError("regen budget file is unreadable")
    found: dict[str, Any] = {}
    for name in ("entries", "count", "late", "over_cap"):
        value = raw.get(name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SettingsError("regen budget file is unreadable")
        found[name] = value
    through = raw.get("through")
    if isinstance(through, int | float) and not isinstance(through, bool):
        found["through"] = float(through)
    return found
