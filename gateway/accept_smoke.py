"""Acceptance smoke: generate_text, then read the call log row back.

The structural check always uses the mock adapter so CI passes with no keys.
When Postgres is reachable the same check is repeated there (Redis when it
answers). HILATV_LIVE=1 plus a vendor key and a positive budget performs one
extra live call.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field

from gateway.budget import limits_from_env
from gateway.cache import MemoryCache, RedisCache, redis_reachable
from gateway.pricing import Pricing
from gateway.registry import build_registry
from gateway.router import RouteTable, default_routes_path
from gateway.service import Gateway
from gateway.store import SqlStore, postgres_reachable


class _SmokeBrief(BaseModel):
    goal: str
    duration_s: int = Field(ge=1, le=600)


def main() -> int:
    try:
        sqlite_summary = _run(
            store=SqlStore.sqlite(_temp_sqlite()),
            cache=MemoryCache(),
            label="sqlite",
        )
        print(json.dumps(sqlite_summary, ensure_ascii=False, default=str))
        require_pg = os.getenv("ACCEPT_T03_REQUIRE_POSTGRES") == "1"
        require_redis = os.getenv("ACCEPT_T03_REQUIRE_REDIS") == "1"
        database_url = os.getenv("DATABASE_URL", "").strip()
        redis_url = os.getenv("REDIS_URL", "").strip()
        pg_up = postgres_reachable(database_url)
        redis_up = redis_reachable(redis_url)
        if require_pg and not pg_up:
            print("postgres required but not reachable", file=sys.stderr)
            return 1
        if require_redis and not redis_up:
            print("redis required but not reachable", file=sys.stderr)
            return 1
        if pg_up:
            cache: MemoryCache | RedisCache
            cache = RedisCache(url=redis_url) if redis_up else MemoryCache()
            summary = _run(store=SqlStore.postgres(database_url), cache=cache, label="postgres")
            summary["redis"] = redis_up
            print(json.dumps(summary, ensure_ascii=False, default=str))
        _maybe_live()
        print("T03 accept smoke: PASS")
        return 0
    except Exception:
        traceback.print_exc()
        return 1


def _run(*, store: SqlStore, cache: MemoryCache | RedisCache, label: str) -> dict[str, object]:
    project_id = f"accept-t03-{uuid.uuid4()}"
    progress = Path(os.environ.get("TMPDIR", "/tmp")) / f"hilatv-accept-{uuid.uuid4()}.md"
    gateway = Gateway(
        routes=RouteTable(default_routes_path()),
        store=store,
        cache=cache,
        pricing=Pricing.load(),
        registry=build_registry(),
        limits_fn=lambda: (False, Decimal("0"), Decimal("0")),
        progress_path=progress,
        model_overrides_fn=lambda: {},
    )
    prompt = "给我们的柱塞泵做个30秒外贸宣传片"
    first = gateway.generate_text(prompt, schema=_SmokeBrief, seed=3, project_id=project_id)
    second = gateway.generate_text(prompt, schema=_SmokeBrief, seed=3, project_id=project_id)
    parsed = _SmokeBrief.model_validate(first)
    if first != second:
        raise AssertionError("same input did not return the same structured JSON")
    logs = store.list_logs(project_id=project_id)
    if len(logs) != 2:
        raise AssertionError(f"expected 2 call_logs rows, got {len(logs)}")
    row = logs[0]
    for column in ("model", "params", "latency_ms", "cost", "status"):
        if column not in row:
            raise AssertionError(f"call log missing {column}")
    if row["qa_score"] is not None:
        raise AssertionError("qa_score is reserved and must be empty")
    if logs[1]["status"] != "cache_hit" or int(logs[1]["cache_hit"]) != 1:
        raise AssertionError(f"second call was not a cache hit: {logs[1]['status']}")
    if Decimal(str(row["cost_cny"])) != 0:
        raise AssertionError("mock call must record cost_cny 0")
    return {
        "label": label,
        "rows": len(logs),
        "model": row["model"],
        "status": row["status"],
        "cache_hit": logs[1]["status"],
        "latency_ms": row["latency_ms"],
        "cost_cny": row["cost_cny"],
        "params_seed": row["params"].get("seed"),
        "goal": parsed.goal,
        "duration_s": parsed.duration_s,
    }


def _maybe_live() -> None:
    live, total, daily = limits_from_env()
    keyed = any(
        os.getenv(name, "").strip()
        for name in ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "ARK_API_KEY")
    )
    if not live or not keyed:
        print("live probe skipped (HILATV_LIVE is off or no LLM key)")
        return
    if total <= 0 or daily <= 0:
        print("live probe skipped (budget is 0, live calls stay on mock)")
        return
    gateway = Gateway.from_env()
    result = gateway.generate_text("Reply with the single word pong.", seed=1)
    if not isinstance(result, dict):
        raise AssertionError("live probe did not return JSON")
    print(json.dumps({"live_probe": result}, ensure_ascii=False, default=str))


def _temp_sqlite() -> str:
    return str(Path(os.environ.get("TMPDIR", "/tmp")) / f"hilatv-accept-{uuid.uuid4()}.sqlite")


if __name__ == "__main__":
    sys.exit(main())
