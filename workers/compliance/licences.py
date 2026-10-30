"""Build the licence bundle delivery is allowed to ship."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from workers.compliance.evidence import screen_evidence
from workers.schemas.licensing import LicenseRecord, LicensingSummary, parse_summary, summarize


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
            usage_scope="本片旁白",
            note="不是人物声音克隆。克隆声必须另有归档授权。",
        ),
    ]


def assemble(
    project_id: str,
    supplied: dict | LicensingSummary | None,
    *,
    root: Path,
    today: date | None = None,
) -> LicensingSummary:
    raw = supplied.model_dump(mode="json") if isinstance(supplied, LicensingSummary) else supplied
    parsed = parse_summary(raw, project_id=project_id)
    records = list(parsed.records)
    present = {record.kind for record in records}
    for item in builtin_records():
        if item.kind not in present:
            records.append(item)
    for record in records:
        screen_evidence(record.evidence_ref, root=root)
        if record.uri.startswith(("http://", "https://", "file:")) or record.uri.startswith("/"):
            screen_evidence(record.uri, root=root)
    return summarize(project_id, records, today=today)
