"""T25: six industry templates, trial shot presets, and mock N1 selection."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError
from templates.validate import ROOT, run_checks

from workers.nodes.n01_brief.industries import load_industries, reset_industries
from workers.nodes.n05_storyboard.presets import ShotPreset, load_presets, reset_presets


def test_accept_checks_pass() -> None:
    report = run_checks()
    assert report.errors == []
    assert report.schema == 6
    assert report.narratives == 6
    assert report.required == 6
    assert report.public_review is True
    assert report.others_clear == 5
    assert report.preset_files >= 17
    assert report.trial == report.preset_files
    assert report.formal == 0
    assert report.selected == 6
    assert report.ok


def test_formal_or_measured_preset_is_rejected() -> None:
    reset_presets()
    sample = load_presets()[0].model_dump()
    with pytest.raises(ValidationError):
        ShotPreset.model_validate({**sample, "status": "正式"})
    with pytest.raises(ValidationError):
        ShotPreset.model_validate({**sample, "formal": True})
    with pytest.raises(ValidationError):
        ShotPreset.model_validate({**sample, "tested_runs": 20})


def test_public_sector_loses_the_flag_and_fails_to_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dest = tmp_path / "industries"
    shutil.copytree(ROOT / "templates" / "industries", dest)
    path = dest / "public_sector.yaml"
    text = path.read_text(encoding="utf-8").replace(
        "manual_review: true",
        "manual_review: false",
        1,
    )
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("HILATV_INDUSTRY_TEMPLATES", str(dest))
    reset_industries()
    try:
        with pytest.raises(ValueError, match="manual_review"):
            load_industries()
    finally:
        reset_industries()


def test_other_industries_cannot_force_manual_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dest = tmp_path / "industries"
    shutil.copytree(ROOT / "templates" / "industries", dest)
    path = dest / "ecommerce.yaml"
    text = path.read_text(encoding="utf-8").replace(
        "manual_review: false",
        "manual_review: true",
        1,
    )
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("HILATV_INDUSTRY_TEMPLATES", str(dest))
    reset_industries()
    try:
        with pytest.raises(ValueError, match="manual_review"):
            load_industries()
    finally:
        reset_industries()
