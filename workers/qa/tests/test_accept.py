"""The acceptance set is built in-process. This locks the 90% line into pytest."""

from __future__ import annotations

from workers.qa.accept import build_report


def test_planted_set_clears_ninety_percent(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_GATEWAY_STORE", "sqlite")
    monkeypatch.setenv("HILATV_SQLITE_PATH", str(tmp_path / "qa.sqlite"))
    monkeypatch.setenv("HILATV_PROGRESS_PATH", str(tmp_path / "progress.md"))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.delenv("REDIS_URL", raising=False)
    from gateway.service import reset_gateway

    reset_gateway()
    try:
        summary = build_report(tmp_path / "set")
    finally:
        reset_gateway()
    assert summary["pass"] is True
    assert float(summary["rate"]) >= 0.9
    assert summary["clean_pass"] == summary["clean"]
    assert summary["visual_passes"] == 0
    assert summary["uncalibrated"] is True
    assert summary["video_deform_veto"] == summary["video_deform"]
    assert summary["calibration"] == "pending_team"
