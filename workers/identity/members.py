"""成员体系（本地 mock）：企业内的成员与角色，离线交接项目。

注意：当前进入系统的方式还是"打开即分配一个企业会话"，没有真正的登录/单点。
成员表先按企业存本地 JSON，供团队设置页与交接使用；等接入登录后换成账号表。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from workers.identity.session import canonical_enterprise

ROLES = {"owner", "editor", "viewer"}


def _root() -> Path:
    raw = os.getenv("HILATV_MEMBER_DIR", "").strip()
    base = Path(raw) if raw else Path(tempfile.gettempdir()) / "hilatv-members"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _path(enterprise_id: str) -> Path:
    return _root() / f"{canonical_enterprise(enterprise_id)}.json"


def _read(enterprise_id: str) -> list[dict[str, Any]]:
    path = _path(enterprise_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _write(enterprise_id: str, rows: list[dict[str, Any]]) -> None:
    _path(enterprise_id).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_members(enterprise_id: str, self_member_id: str) -> list[dict[str, Any]]:
    rows = _read(enterprise_id)
    if not any(row.get("member_id") == self_member_id for row in rows):
        rows.insert(
            0,
            {
                "member_id": self_member_id,
                "name": "我自己",
                "role": "owner",
                "status": "active",
                "created_at": time.time(),
            },
        )
        _write(enterprise_id, rows)
    return rows


def add_member(enterprise_id: str, name: str, role: str) -> dict[str, Any]:
    if role not in ROLES:
        raise ValueError("角色不对")
    text = name.strip()
    if not text:
        raise ValueError("先写成员名字")
    rows = _read(enterprise_id)
    row = {
        "member_id": uuid.uuid4().hex,
        "name": text[:40],
        "role": role,
        "status": "active",
        "created_at": time.time(),
    }
    rows.append(row)
    _write(enterprise_id, rows)
    return row


def update_member(
    enterprise_id: str, member_id: str, *, role: str | None, status: str | None
) -> dict[str, Any]:
    rows = _read(enterprise_id)
    for row in rows:
        if row.get("member_id") != member_id:
            continue
        if role is not None:
            if role not in ROLES:
                raise ValueError("角色不对")
            row["role"] = role
        if status is not None:
            if status not in {"active", "departed"}:
                raise ValueError("状态不对")
            row["status"] = status
        _write(enterprise_id, rows)
        return row
    raise LookupError("没有这个成员")


def remove_member(enterprise_id: str, member_id: str) -> None:
    rows = [row for row in _read(enterprise_id) if row.get("member_id") != member_id]
    _write(enterprise_id, rows)


def handover_projects(departing_member_id: str, to_member_id: str, enterprise_id: str) -> int:
    """把离职成员名下的项目改到接手人名下，返回改了几个。"""

    from workers.workflow.store import (
        project_root,
        read_snapshot,
        update_snapshot,
        valid_project_id,
    )

    root = project_root()
    moved = 0
    if not root.is_dir():
        return moved
    for entry in root.iterdir():
        if not entry.is_dir() or not valid_project_id(entry.name):
            continue
        snapshot = read_snapshot(entry.name)
        if not snapshot or snapshot.get("enterprise_id") != enterprise_id:
            continue
        if snapshot.get("owner_member_id") != departing_member_id:
            continue
        update_snapshot(entry.name, owner_member_id=to_member_id)
        moved += 1
    return moved
