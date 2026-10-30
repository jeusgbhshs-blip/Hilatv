"""T21's licence JSON loads, and gaps or expiry block delivery."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from workers.schemas.director import RevisionDirective
from workers.schemas.licensing import LicenseRecord, LicensingSummary, block_reason, summarize


def test_t21_music_record_loads() -> None:
    raw = {
        "record_id": "bed-1",
        "kind": "music",
        "source": "hilatv-test-library",
        "license": "commercial-library",
        "title": "workshop bed",
        "uri": "library://bed",
        "start_s": 0,
        "duration_s": 12,
        "shot_id": None,
        "note": "",
    }
    record = LicenseRecord.model_validate(raw)
    summary = LicensingSummary.model_validate(
        {"project_id": "p1", "records": [raw], "blocked": False, "block_reason": ""}
    )
    assert record.kind == "music"
    assert record.license == "commercial-library"
    assert summary.records[0].source == "hilatv-test-library"
    assert block_reason(summary.records, today=date(2026, 10, 30)) == ""


def test_type_and_licence_aliases() -> None:
    record = LicenseRecord.model_validate(
        {
            "record_id": "font-1",
            "type": "font",
            "source": "vendor",
            "licence": "OFL-1.1",
            "evidence": "docs/licenses.md#noto",
            "scope": "本片字幕",
            "expires_on": "2026-12-31",
        }
    )
    assert record.kind == "font"
    assert record.license == "OFL-1.1"
    assert record.evidence_ref == "docs/licenses.md#noto"
    assert record.usage_scope == "本片字幕"
    assert record.expires_on == date(2026, 12, 31)


def test_missing_source_or_licence_blocks() -> None:
    reason = block_reason(
        [
            LicenseRecord(
                record_id="m1",
                kind="music",
                source="",
                license="commercial",
            )
        ],
        today=date(2026, 10, 30),
    )
    assert "missing a source or a license" in reason
    summary = summarize(
        "p1",
        [LicenseRecord(record_id="m2", kind="sfx", source="lib", license="")],
        today=date(2026, 10, 30),
    )
    assert summary.blocked is True


def test_expired_licence_blocks_and_today_is_still_valid() -> None:
    expired = LicenseRecord(
        record_id="m1",
        kind="music",
        source="lib",
        license="commercial",
        expires_on=date(2026, 10, 1),
    )
    assert "expired" in block_reason([expired], today=date(2026, 10, 30))
    current = expired.model_copy(update={"expires_on": date(2026, 10, 30)})
    assert block_reason([current], today=date(2026, 10, 30)) == ""
    open_ended = expired.model_copy(update={"expires_on": None})
    assert block_reason([open_ended], today=date(2026, 10, 30)) == ""


def test_revision_cannot_remove_the_ai_label() -> None:
    with pytest.raises(ValidationError, match="AI生成"):
        RevisionDirective.model_validate(
            {"targets": ["S01"], "change": {"instruction": "去掉 AI 标识"}, "keep": ["composition"]}
        )


def test_ordinary_revision_still_loads() -> None:
    directive = RevisionDirective.model_validate(
        {"targets": ["S02"], "change": {"lighting": "brighter"}, "keep": ["composition"]}
    )
    assert directive.change["lighting"] == "brighter"
