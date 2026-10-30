"""N12's licence row is the only one. Delivery adds the expiry and live checks."""

from __future__ import annotations

from datetime import date

import pytest

from workers.compliance.licences import (
    LicenseRecord as DeliveryRecord,
)
from workers.compliance.licences import (
    delivery_block_reason,
)
from workers.nodes.n12_music.schema import LicenseRecord, LicensingSummary, incomplete_reason


def test_delivery_uses_the_n12_class() -> None:
    assert DeliveryRecord is LicenseRecord


def test_t21_music_record_loads() -> None:
    raw = {
        "record_id": "bed-1",
        "kind": "music",
        "source": "hilatv-test-library",
        "license": "commercial-library",
        "evidence_ref": "contract-1",
        "expires_on": "none",
        "usage_scope": "本片背景音乐",
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
    assert summary.records[0].evidence_ref == "contract-1"
    assert incomplete_reason(summary.records) == ""
    assert delivery_block_reason(summary.records, today=date(2026, 10, 30)) == ""


def test_missing_source_or_evidence_blocks() -> None:
    bare = [
        LicenseRecord(
            record_id="m1",
            kind="music",
            source="",
            license="commercial",
        )
    ]
    assert "missing a source or a license" in incomplete_reason(bare)
    thin = [
        LicenseRecord(
            record_id="m2",
            kind="sfx",
            source="lib",
            license="commercial",
            evidence_ref="",
            expires_on="none",
            usage_scope="本片",
        )
    ]
    assert "evidence" in incomplete_reason(thin)


def test_expired_licence_blocks_and_today_and_none_stay_valid() -> None:
    today = date(2026, 10, 30)
    base = dict(
        record_id="m1",
        kind="music",
        source="lib",
        license="commercial",
        evidence_ref="contract-1",
        usage_scope="本片",
    )
    expired = LicenseRecord(**base, expires_on="2026-10-01")
    assert "expired" in delivery_block_reason([expired], today=today)
    current = LicenseRecord(**base, expires_on="2026-10-30")
    assert delivery_block_reason([current], today=today) == ""
    open_ended = LicenseRecord(**base, expires_on="none")
    assert delivery_block_reason([open_ended], today=today) == ""


def test_live_mode_rejects_the_test_library(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "1")
    record = LicenseRecord(
        record_id="bed",
        kind="music",
        source="hilatv-test-library/steady",
        license="CC0-1.0",
        evidence_ref="workers/nodes/n12_music/library.py",
        expires_on="none",
        usage_scope="internal-test-mock-only",
    )
    reason = delivery_block_reason([record], today=date(2026, 10, 30))
    assert reason == "live mode cannot deliver the mock test-library licence"
