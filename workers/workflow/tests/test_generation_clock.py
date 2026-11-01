"""New whole-film clocks are forwarded consistently; old histories stay compatible."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from workers.workflow import activities, revise

FIXTURES = Path(__file__).resolve().parents[2] / "schemas" / "tests" / "fixtures"


def fixture_brief():
    brief = json.loads((FIXTURES / "brief.json").read_text())
    brief.update(duration_s=15, aspect_ratios=["4:3"], languages=["zh"])
    return brief


@pytest.mark.parametrize("target,outro", [(5, 1), (6, 2), (15, 2.4), (30, 2.4), (180, 2.4)])
def test_clock_reserves_packaging_and_retains_the_requested_total(target, outro):
    payload = {
        "request": {"generation_settings": {"duration_s": target, "aspect_ratio": "4:3"}},
        "state": {"brief": fixture_brief()},
    }
    clock = activities.production_clock(payload)
    assert clock == {"target_duration_s": target, "intro_s": 0, "outro_s": outro}
    assert activities.story_clock(payload)["story_duration_s"] == pytest.approx(target - outro)
    assert payload["request"]["generation_settings"]["duration_s"] == target


def test_automatic_new_settings_use_the_resolved_time_but_legacy_history_does_not():
    state = {"brief": fixture_brief()}
    assert activities.production_clock({"request": {}, "state": state}) == {}
    assert (
        activities.production_clock({"request": {"generation_settings": None}, "state": state})
        == {}
    )
    assert (
        activities.production_clock({"request": {"generation_settings": {}}, "state": state})[
            "target_duration_s"
        ]
        == 15
    )


def test_activity_brief_carries_saved_choices_and_public_resolved_target(monkeypatch):
    from workers.nodes.n01_brief import node

    received = {}
    published = {}

    def run(raw, **kwargs):
        received.update(raw)
        return SimpleNamespace(payload={"brief": fixture_brief()})

    monkeypatch.setattr(node, "run", run)
    monkeypatch.setattr(activities, "_announce", lambda *args: 1)
    monkeypatch.setattr(activities, "_finish", lambda _id, _node, patch, _attempt: patch)
    monkeypatch.setattr(
        activities, "update_snapshot", lambda _id, **fields: published.update(fields)
    )
    settings = {"aspect_ratio": "4:3", "duration_s": 15}
    result = activities.n01_brief(
        {
            "project_id": "clock-node",
            "request": {"sentence": "竖版30秒", "generation_settings": settings},
            "state": {},
        }
    )
    assert received["payload"]["generation_settings"] == settings
    assert result["brief"]["duration_s"] == 15
    assert published["resolved_generation_settings"] == {
        "aspect_ratio": "4:3",
        "duration_s": 15,
        "language": "zh",
    }
    assert "width" not in published and "height" not in published


def test_revision_uses_the_archived_frame_instead_of_a_wide_environment(monkeypatch):
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "320")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "180")
    width, height = revise._canvas(fixture_brief())
    assert width * 3 == height * 4


def test_revision_compose_keeps_the_whole_film_clock(monkeypatch, tmp_path):
    from workers.nodes.n15_compose import node

    captured = {}

    def run(raw, **kwargs):
        captured.update(raw["payload"])
        return SimpleNamespace(
            payload={
                "exports": {
                    "master": str(tmp_path / "new.mp4"),
                    "clean_picture": str(tmp_path / "new-clean.mp4"),
                },
                "timeline": {"duration_s": 15},
                "script": {"shots": [{"shot_id": "rendered"}]},
            }
        )

    monkeypatch.setattr(node, "run", run)
    script = SimpleNamespace(model_dump=lambda **kwargs: {"shots": []})
    clock = {"target_duration_s": 15, "intro_s": 0, "outro_s": 2.4}
    rendered = {}
    result = revise._compose(
        tmp_path,
        "revision-clock",
        script,
        [],
        [],
        [],
        None,
        fixture_brief(),
        0,
        2.4,
        320,
        240,
        clock=clock,
        render_result=rendered,
    )
    assert result == str(tmp_path / "new.mp4")
    assert captured["target_duration_s"] == 15
    assert (captured["width"], captured["height"]) == (320, 240)
    assert captured["outro_s"] == 2.4
    assert rendered["exports"]["clean_picture"] == str(tmp_path / "new-clean.mp4")
    assert rendered["timeline"]["duration_s"] == 15
    assert rendered["script"]["shots"][0]["shot_id"] == "rendered"
