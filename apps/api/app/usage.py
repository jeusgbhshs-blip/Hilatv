"""用量与账单：读现有预算账本（mock 下费用为 0）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.identity import require_identity
from workers.identity.session import Identity
from workers.qa.budget_store import open_project_budget
from workers.workflow.store import project_root, read_snapshot, valid_project_id

router = APIRouter()


@router.get("/v1/usage")
def usage(identity: Identity = Depends(require_identity)) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total_used = 0
    total_limit = 0
    root = project_root()
    if root.is_dir():
        for entry in root.iterdir():
            if not entry.is_dir() or not valid_project_id(entry.name):
                continue
            snapshot = read_snapshot(entry.name)
            if not snapshot or snapshot.get("enterprise_id") != identity.enterprise_id:
                continue
            budget = open_project_budget(entry.name)
            total_used += budget.used
            total_limit += budget.limit
            rows.append(
                {
                    "project_id": entry.name,
                    "sentence": snapshot.get("sentence") or "",
                    "status": snapshot.get("status") or "",
                    "used": budget.used,
                    "limit": budget.limit,
                    "remaining": max(0, budget.limit - budget.used),
                }
            )
    rows.sort(key=lambda item: item["used"], reverse=True)
    return {
        "budget": {
            "used": total_used,
            "limit": total_limit,
            "remaining": max(0, total_limit - total_used),
        },
        "projects": rows,
        "note": "测试环境走 mock，费用按 0 记；接真实模型后按网关调用日志统计。",
    }
