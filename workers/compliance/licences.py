"""Build the licence bundle delivery is allowed to ship.

Rows are N12's ``LicenseRecord``. This module does not define another one.
``expires_on`` is the string N12 stores: an ISO date, or ``none`` when the
grant does not expire. A date before today (Asia/Shanghai, today still valid)
blocks delivery. ``HILATV_LIVE=1`` also rejects the mock test-library licence,
the same rule N12 uses when it writes the row.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from workers.compliance.evidence import screen_evidence
from workers.nodes.n12_music.schema import (
    LicenseRecord,
    LicensingSummary,
    incomplete_reason,
)

__all__ = [
    "LicenseRecord",
    "LicensingSummary",
    "assemble",
    "builtin_records",
    "delivery_block_reason",
    "today_shanghai",
]


def today_shanghai(now: datetime | None = None) -> date:
    moment = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return moment.astimezone(ZoneInfo("Asia/Shanghai")).date()


def builtin_records() -> list[LicenseRecord]:
    """Font and stock voice the render layer always uses. Not a music grant."""

    return [
        LicenseRecord(
            record_id="font-noto-sans-cjk-sc",
            kind="font",
            source="templates/packaging/fonts (Noto Sans CJK SC, Adobe / Noto CJK)",
            license="SIL OFL 1.1",
            title="Noto Sans CJK SC",
            evidence_ref="docs/licenses.md#noto-sans-cjk-sc",
            expires_on="none",
            usage_scope="本片字幕、卖点卡、片尾和 AI 显式标识",
            note="推断: 字型授权只覆盖随仓库分发的 OFL 字体文件。",
        ),
        LicenseRecord(
            record_id="voice-stock-tts",
            kind="voice",
            source="gateway:tts",
            license="stock-voice-not-a-clone",
            title="旁白",
            evidence_ref="gateway mock or vendor TTS route",
            expires_on="none",
            usage_scope="本片旁白",
            note="不是人物声音克隆。克隆声必须另有归档授权。",
        ),
    ]


def delivery_block_reason(records: list[LicenseRecord], *, today: date | None = None) -> str:
    """Empty when every row is complete, unexpired, and allowed in this mode."""

    reason = incomplete_reason(records)
    if reason:
        return reason
    current = today or today_shanghai()
    live = os.getenv("HILATV_LIVE", "0").strip() == "1"
    for record in records:
        label = record.shot_id or record.record_id
        if live and _test_library(record):
            return "live mode cannot deliver the mock test-library licence"
        raw = record.expires_on.strip()
        if raw.lower() == "none":
            continue
        try:
            expiry = date.fromisoformat(raw)
        except ValueError:
            return f"{record.kind} {label} has an expiry that is not an ISO date or none"
        if expiry < current:
            return f"{record.kind} {label} licence expired on {expiry.isoformat()}"
    return ""


def assemble(
    project_id: str,
    supplied: dict[str, Any] | LicensingSummary | None,
    *,
    root: Path,
    today: date | None = None,
) -> LicensingSummary:
    records = _supplied(project_id, supplied)
    present = {record.kind for record in records}
    for item in builtin_records():
        if item.kind not in present:
            records.append(item)
    for record in records:
        screen_evidence(record.evidence_ref, root=root)
        if record.uri.startswith(("http://", "https://", "file:")) or record.uri.startswith("/"):
            screen_evidence(record.uri, root=root)
    reason = delivery_block_reason(records, today=today)
    return LicensingSummary(
        project_id=project_id,
        records=records,
        blocked=bool(reason),
        block_reason=reason,
    )


def _supplied(
    project_id: str,
    supplied: dict[str, Any] | LicensingSummary | None,
) -> list[LicenseRecord]:
    if supplied is None:
        return []
    if isinstance(supplied, LicensingSummary):
        return list(supplied.records)
    data = dict(supplied)
    data.setdefault("project_id", project_id)
    data.setdefault("records", [])
    return list(LicensingSummary.model_validate(data).records)


def _test_library(record: LicenseRecord) -> bool:
    return record.source.startswith("hilatv-test-") or record.license == "CC0-1.0"
