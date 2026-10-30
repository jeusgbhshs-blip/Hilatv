"""QA thresholds fail closed. A bad value is an error, not a quieter default."""

from __future__ import annotations

import pytest

from workers.qa.service import review_shot
from workers.qa.settings import SettingsError, project_retry_cap, validate_settings
from workers.qa.tests.conftest import MockGateway


def test_defaults_are_inside_the_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HILATV_QA_DEFORM_MIN_SIMILARITY",
        "HILATV_QA_FACE_MIN_SIMILARITY",
        "HILATV_QA_MIN_EDGE",
        "HILATV_QA_FLICKER_DELTA",
        "HILATV_QA_FLICKER_NEIGHBOR",
        "HILATV_QA_PROJECT_RETRIES",
    ):
        monkeypatch.delenv(name, raising=False)
    validate_settings()
    assert project_retry_cap() >= 1


def test_similarity_outside_the_unit_interval_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_QA_DEFORM_MIN_SIMILARITY", "0")
    with pytest.raises(SettingsError, match=r"HILATV_QA_DEFORM_MIN_SIMILARITY must be in \(0, 1\]"):
        validate_settings()
    monkeypatch.setenv("HILATV_QA_DEFORM_MIN_SIMILARITY", "1.5")
    with pytest.raises(SettingsError, match="1.5"):
        validate_settings()
    monkeypatch.setenv("HILATV_QA_FACE_MIN_SIMILARITY", "nope")
    monkeypatch.setenv("HILATV_QA_DEFORM_MIN_SIMILARITY", "0.9")
    with pytest.raises(SettingsError, match="HILATV_QA_FACE_MIN_SIMILARITY must be a number"):
        validate_settings()
    monkeypatch.setenv("HILATV_QA_FLICKER_DELTA", "0")
    monkeypatch.setenv("HILATV_QA_FACE_MIN_SIMILARITY", "0.75")
    with pytest.raises(SettingsError, match="HILATV_QA_FLICKER_DELTA"):
        validate_settings()


def test_infinite_retry_cap_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "inf")
    with pytest.raises(SettingsError, match="HILATV_QA_PROJECT_RETRIES must be an integer >= 1"):
        validate_settings()
    monkeypatch.setenv("HILATV_QA_MIN_EDGE", "nan")
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "12")
    with pytest.raises(SettingsError, match="HILATV_QA_MIN_EDGE"):
        validate_settings()


def test_caps_below_one_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_QA_MIN_EDGE", "0")
    with pytest.raises(SettingsError, match="HILATV_QA_MIN_EDGE must be an integer >= 1"):
        validate_settings()
    monkeypatch.setenv("HILATV_QA_MIN_EDGE", "240")
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "0")
    with pytest.raises(SettingsError, match="HILATV_QA_PROJECT_RETRIES"):
        validate_settings()


def test_review_refuses_to_start_when_a_threshold_is_bad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HILATV_QA_DEFORM_MIN_SIMILARITY", "2")
    with pytest.raises(SettingsError, match="HILATV_QA_DEFORM_MIN_SIMILARITY"):
        review_shot(
            {"project_id": "p", "shot_id": "S01", "node": "n09_keyframe", "text_only": True},
            gateway=MockGateway(),
        )
