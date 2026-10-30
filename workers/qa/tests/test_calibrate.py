"""Calibration stays pending until the team supplies 200 ranked images."""

from __future__ import annotations

import json

import pytest

from workers.qa.calibrate import calibration_status, pairwise_agreement
from workers.qa.final import review_film


def test_missing_manifest_is_pending() -> None:
    status = calibration_status()
    assert status["status"] == "pending_team"
    assert status["expected"] == 200
    assert status["have"] == 0
    assert status["agreement"] is None


def test_pairwise_agreement_and_a_full_set_is_gated(tmp_path) -> None:
    assert pairwise_agreement(["a", "b", "c"], ["a", "b", "c"]) == 1
    assert pairwise_agreement(["a", "b", "c"], ["c", "b", "a"]) == 0
    short = tmp_path / "manifest.json"
    short.write_text(
        json.dumps(
            {
                "count": 3,
                "images": ["a", "b", "c"],
                "rankings": [{"human": ["a", "b", "c"], "judge": ["a", "b", "c"]}],
            }
        ),
        encoding="utf-8",
    )
    assert calibration_status(manifest=short)["status"] == "pending_team"
    full = tmp_path / "full.json"
    full.write_text(
        json.dumps(
            {
                "count": 200,
                "images": [str(index) for index in range(200)],
                "rankings": [{"human": ["a", "b"], "judge": ["b", "a"]}],
            }
        ),
        encoding="utf-8",
    )
    failed = calibration_status(manifest=full)
    assert failed["status"] == "fail"
    assert failed["agreement"] == 0
    full.write_text(
        json.dumps(
            {
                "count": 200,
                "images": [str(index) for index in range(200)],
                "rankings": [{"human": ["a", "b", "c"], "judge": ["a", "c", "b"]}],
            }
        ),
        encoding="utf-8",
    )
    # One pair of three is reversed (b before c vs c before b): agreement 2/3.
    assert calibration_status(manifest=full)["status"] == "fail"
    full.write_text(
        json.dumps(
            {
                "count": 200,
                "images": [str(index) for index in range(200)],
                "rankings": [{"human": ["a", "b", "c"], "judge": ["a", "b", "c"]}],
            }
        ),
        encoding="utf-8",
    )
    assert calibration_status(manifest=full)["status"] == "pass"


def test_n16_review_needs_a_brief_and_a_script() -> None:
    with pytest.raises(ValueError, match="brief"):
        review_film({"project_id": "p"})
