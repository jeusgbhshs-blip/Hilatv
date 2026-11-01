"""Budget guard. Live calls stop when the total or Shanghai-day cap is hit."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gateway.clock import SystemClock
from gateway.constants import ALERT_HEADING, ALERT_MARKER, DAILY_LOG_HEADING
from gateway.logging import log_event
from gateway.money import money, money_upper
from gateway.store import SqlStore

LimitsFn = Callable[[], tuple[bool, Decimal, Decimal]]


@dataclass
class BudgetDecision:
    allowed: bool
    reason: str
    notify: bool
    spent: Decimal
    limit: Decimal
    daily_spent: Decimal
    daily_limit: Decimal
    estimate: Decimal
    reservation_id: str | None = None
    reserved: Decimal = Decimal("0")


class BudgetGuard:
    def __init__(
        self,
        *,
        store: SqlStore,
        limits_fn: LimitsFn,
        clock: SystemClock | Any,
        progress_path: Path | None,
        tz: str = "Asia/Shanghai",
    ) -> None:
        self.store = store
        self.limits_fn = limits_fn
        self.clock = clock
        self.progress_path = progress_path
        self.tz = tz

    def evaluate(self, estimate: Decimal) -> BudgetDecision:
        live, total_cap, daily_cap = self.limits_fn()
        total_cap = money(total_cap)
        daily_cap = money(daily_cap)
        estimate = money(estimate)
        today = self.today()
        totals = self.store.budget_totals(today)
        spent = totals["spent"]
        daily_spent = totals["daily_spent"]
        held = totals["reserved"]
        if not live:
            return BudgetDecision(
                False,
                "live_off",
                False,
                spent,
                total_cap,
                daily_spent,
                daily_cap,
                estimate,
                reserved=held,
            )
        if total_cap <= 0 or spent + held >= total_cap or spent + held + estimate > total_cap:
            return BudgetDecision(
                False,
                "total",
                True,
                spent,
                total_cap,
                daily_spent,
                daily_cap,
                estimate,
                reserved=held,
            )
        if (
            daily_cap <= 0
            or daily_spent + held >= daily_cap
            or daily_spent + held + estimate > daily_cap
        ):
            return BudgetDecision(
                False,
                "daily",
                True,
                spent,
                daily_cap,
                daily_spent,
                daily_cap,
                estimate,
                reserved=held,
            )
        return BudgetDecision(
            True, "ok", False, spent, total_cap, daily_spent, daily_cap, estimate, reserved=held
        )

    def reserve(self, estimate: Decimal, **context: object) -> BudgetDecision:
        """Admission is atomic with other processes, including outstanding calls."""
        live, total_cap, daily_cap = self.limits_fn()
        if not live:
            return self.evaluate(estimate)
        reservation_id = str(uuid.uuid4())
        total_cap, daily_cap, estimate = money(total_cap), money(daily_cap), money_upper(estimate)
        result = self.store.reserve_budget(
            reservation_id=reservation_id,
            day=self.today(),
            created_at=self.clock.now().isoformat(),
            estimate=estimate,
            total_cap=total_cap,
            daily_cap=daily_cap,
            context=dict(context),
            admission_time=self._admission_time,
        )
        return BudgetDecision(
            result["allowed"],
            result["reason"],
            not result["allowed"],
            result["spent"],
            daily_cap if result["reason"] == "daily" else total_cap,
            result["daily_spent"],
            daily_cap,
            estimate,
            reservation_id if result["allowed"] else None,
            result["reserved"],
        )

    def notify(self, decision: BudgetDecision, **context: object) -> None:
        now = self.clock.now()
        line = format_alert(now, decision)
        log_event(
            "budget_exceeded",
            spent_cny=decision.spent if decision.reason == "total" else decision.daily_spent,
            limit_cny=decision.limit,
            daily_spent_cny=decision.daily_spent,
            daily_limit_cny=decision.daily_limit,
            total_spent_cny=decision.spent,
            total_limit_cny=decision.limit if decision.reason == "total" else None,
            reason=decision.reason,
            reserved_cny=decision.reserved,
            estimate_cny=decision.estimate,
            ts=now.isoformat(),
            project_id=context.get("project_id"),
            node=context.get("node"),
            shot_id=context.get("shot_id"),
            attempt=context.get("attempt"),
        )
        self.store.insert_alert(
            {
                "created_at": now.isoformat(),
                "kind": "budget_exceeded",
                "message": line,
                "spent_cny": decision.spent if decision.reason == "total" else decision.daily_spent,
                "limit_cny": decision.limit,
                "daily_spent_cny": decision.daily_spent,
                "daily_limit_cny": decision.daily_limit,
                "details": {
                    "reason": decision.reason,
                    "estimate_cny": format(decision.estimate, "f"),
                    "reserved_cny": format(decision.reserved, "f"),
                    "total_spent_cny": format(decision.spent, "f"),
                    "total_limit_cny": format(
                        decision.limit if decision.reason == "total" else money(0), "f"
                    ),
                    "project_id": context.get("project_id"),
                    "node": context.get("node"),
                    "shot_id": context.get("shot_id"),
                },
            }
        )
        if self.progress_path is not None:
            append_progress_alert(self.progress_path, line)

    def today(self) -> str:
        return self.clock.now().astimezone(ZoneInfo(self.tz)).date().isoformat()

    def _admission_time(self) -> tuple[str, str]:
        now = self.clock.now()
        return now.astimezone(ZoneInfo(self.tz)).date().isoformat(), now.isoformat()


def limits_from_env() -> tuple[bool, Decimal, Decimal]:
    live = os.getenv("HILATV_LIVE", "0").strip() == "1"
    return live, _env_money("HILATV_BUDGET_CNY"), _env_money("HILATV_DAILY_BUDGET_CNY")


def env_model_overrides() -> dict[str, str]:
    return {
        "deepseek": os.getenv("DEEPSEEK_MODEL", "").strip(),
        "dashscope": os.getenv("DASHSCOPE_MODEL", "").strip(),
        "ark": os.getenv("ARK_MODEL", "").strip(),
        "seedream": os.getenv("SEEDREAM_MODEL", "").strip(),
        "seedance": os.getenv("SEEDANCE_MODEL", "").strip(),
        "volc_tts": os.getenv("VOLC_TTS_MODEL", "").strip(),
        "qwen_vl": os.getenv("QWEN_VL_MODEL", "").strip(),
        "gemini": os.getenv("GEMINI_MODEL", "").strip(),
    }


def format_alert(now: datetime, decision: BudgetDecision) -> str:
    spent = decision.spent if decision.reason == "total" else decision.daily_spent
    label = {"total": "总上限", "daily": "每日上限"}.get(decision.reason, "费用上界失效")
    return (
        f"- {now.strftime('%Y-%m-%d %H:%M')} budget_exceeded："
        f"已花费 ¥{spent} / 上限 ¥{decision.limit}"
        f"（当日 ¥{decision.daily_spent} / ¥{decision.daily_limit}，{label}），"
        "live 调用已暂停并回退 mock"
    )


def append_progress_alert(path: Path, line: str) -> None:
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{ALERT_HEADING}\n\n{ALERT_MARKER}\n{line}\n", encoding="utf-8")
            return
        text = path.read_text(encoding="utf-8")
        if line in text:
            return
        if ALERT_MARKER in text:
            text = text.replace(ALERT_MARKER, f"{ALERT_MARKER}\n{line}", 1)
        elif DAILY_LOG_HEADING in text:
            text = text.replace(DAILY_LOG_HEADING, f"{line}\n\n{DAILY_LOG_HEADING}", 1)
        else:
            text = text.rstrip() + "\n" + line + "\n"
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        log_event("progress_alert_failed", path=str(path), error=str(exc))


def _env_money(name: str) -> Decimal:
    raw = os.getenv(name, "")
    if raw is None or str(raw).strip() == "":
        return money(0)
    return money(raw)
