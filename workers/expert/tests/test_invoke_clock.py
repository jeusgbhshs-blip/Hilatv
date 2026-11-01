"""Expert runners forward one production clock without starting real providers."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from workers.expert import invoke
from workers.expert.gates import GateError

CLOCK = {"target_duration_s": 15.0, "intro_s": 0.0, "outro_s": 1.0}
SETTINGS = {"aspect_ratio": "9:16", "duration_s": 15}


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    clock_calls: list[dict[str, Any]] = []
    story_calls: list[dict[str, Any]] = []
    font_calls: list[bool] = []

    def clock(payload):
        clock_calls.append(payload)
        return dict(CLOCK) if payload["request"]["generation_settings"] is not None else {}

    def story(payload):
        story_calls.append(payload)
        return {"story_duration_s": 14.0} if payload["request"]["generation_settings"] else {}

    monkeypatch.setattr(invoke, "production_clock", clock)
    monkeypatch.setattr(invoke, "story_clock", story)
    monkeypatch.setattr(invoke, "enforce_fonts", lambda: font_calls.append(True))
    monkeypatch.setattr("workers.workflow.film.needs_human_review", lambda *_: False)
    state = {
        "brief": {"duration_s": 15, "style": "沉稳"},
        "script": {"shots": [{"shot_id": "S01", "order": 1, "duration_s": 3.0}]},
        "intro_s": 0.0,
        "outro_s": 1.0,
    }
    return SimpleNamespace(
        state=state,
        snapshot={"sentence": "十五秒产品宣传", "generation_settings": dict(SETTINGS)},
        gateway=object(),
        clock_calls=clock_calls,
        story_calls=story_calls,
        font_calls=font_calls,
        root=tmp_path,
    )


def fake_node(monkeypatch, name: str, context, payload: dict[str, Any]):
    calls = []

    def run(raw, **kwargs):
        calls.append(raw)
        assert kwargs == {
            "timeout_s": invoke.node_timeout(name),
            "max_attempts": 1,
            "gateway": context.gateway,
        }
        return SimpleNamespace(payload=payload)

    module = importlib.import_module(f"workers.nodes.{name}.node")
    monkeypatch.setattr(module, "run", run)
    return calls


def run_node(context, name: str, *, shot_id: str | None = None):
    return invoke.invoke_node(
        name,
        project_id="clock-project",
        state=context.state,
        snapshot=context.snapshot,
        shot_id=shot_id,
        gateway=context.gateway,
        enterprise_id="enterprise-a",
    )


def test_n01_forwards_saved_generation_settings_and_auto_for_legacy(context, monkeypatch):
    calls = fake_node(monkeypatch, "n01_brief", context, {"brief": context.state["brief"]})
    run_node(context, "n01_brief")
    assert calls[0]["payload"]["generation_settings"] == SETTINGS
    context.snapshot.pop("generation_settings")
    run_node(context, "n01_brief")
    assert calls[1]["payload"]["generation_settings"] == {}


@pytest.mark.parametrize("node", ["n04_script", "n05_storyboard"])
def test_story_runners_forward_body_budget_and_n04_saves_clock(context, monkeypatch, node):
    calls = fake_node(monkeypatch, node, context, {"script": context.state["script"]})
    patch = run_node(context, node)
    assert calls[0]["payload"]["story_duration_s"] == 14.0
    assert "target_duration_s" not in calls[0]["payload"]
    assert context.story_calls == [
        {
            "request": {"generation_settings": SETTINGS},
            "state": context.state,
        }
    ]
    assert context.story_calls[0]["state"] is context.state
    if node == "n04_script":
        assert patch["production_clock"] == CLOCK
    else:
        assert patch["shot_summaries"] == [{"shot_id": "S01", "order": 1, "purpose": ""}]


@pytest.mark.parametrize("node", ["n06_voiceover", "n12_music", "n14_packaging"])
def test_whole_film_runners_forward_the_complete_production_clock(context, monkeypatch, node):
    payload = {
        "script": context.state["script"],
        "voiceovers": [],
        "audio_track": {"path": "server-owned-mix.wav"},
        "licensing_summary": {},
        "aligned_script": context.state["script"],
        "elements": [{"kind": "ai_label", "text": "AI生成"}],
        "intro_s": 0.0,
        "outro_s": 1.0,
    }
    calls = fake_node(monkeypatch, node, context, payload)
    run_node(context, node)
    assert {key: calls[0]["payload"][key] for key in CLOCK} == CLOCK
    assert context.clock_calls == [
        {
            "request": {"generation_settings": SETTINGS},
            "state": context.state,
        }
    ]
    if node == "n14_packaging":
        assert context.font_calls == [True]


def test_single_shot_voice_rerun_never_receives_the_whole_film_clock(context, monkeypatch):
    calls = fake_node(
        monkeypatch,
        "n06_voiceover",
        context,
        {
            "script": context.state["script"],
            "voiceovers": [],
        },
    )
    run_node(context, "n06_voiceover", shot_id="S01")
    assert calls[0]["shot_id"] == "S01"
    assert calls[0]["payload"]["script"]["shots"][0]["duration_s"] == 3.0
    assert not set(CLOCK).intersection(calls[0]["payload"])
    assert context.clock_calls == []


def test_legacy_whole_film_rerun_does_not_invent_a_new_target(context, monkeypatch):
    context.snapshot.pop("generation_settings")
    calls = fake_node(monkeypatch, "n04_script", context, {"script": context.state["script"]})
    patch = run_node(context, "n04_script")
    assert "story_duration_s" not in calls[0]["payload"]
    assert patch["production_clock"] == {}


def compose_node(context, monkeypatch, *, label=True):
    calls = []

    def run(raw, **kwargs):
        assert kwargs["gateway"] is context.gateway
        work = Path(raw["payload"]["work_dir"])
        work.mkdir(parents=True)
        (work / "master.mp4").write_bytes(b"new attempt only")
        calls.append(raw)
        return SimpleNamespace(
            payload={
                "exports": {
                    "master": str(work / "master.mp4"),
                    "clean_picture": str(work / "clean-picture.mp4"),
                },
                "timeline": {
                    "width": 720,
                    "height": 1280,
                    "duration_s": 15.0,
                    "overlays": [{"kind": "ai_label", "text": "AI生成"}] if label else [],
                },
                "timeline_path": str(work / "timeline.json"),
            }
        )

    monkeypatch.setattr("workers.nodes.n15_compose.node.run", run)
    return calls


def test_compose_uses_actual_packaging_and_immutable_attempts_with_clean_picture(
    context, monkeypatch
):
    previous = context.root / "clock-project" / "render" / "n15" / "master.mp4"
    previous.parent.mkdir(parents=True)
    previous.write_bytes(b"previous approved bytes")
    context.state.update(intro_s=0.01, outro_s=1.01)
    calls = compose_node(context, monkeypatch)
    first = run_node(context, "n15_compose")
    second = run_node(context, "n15_compose")
    for call, patch in zip(calls, (first, second), strict=True):
        payload = call["payload"]
        assert payload["target_duration_s"] == 15.0
        assert payload["intro_s"] == 0.01
        assert payload["outro_s"] == 1.01
        assert Path(payload["work_dir"]).parent == previous.parent / "renders"
        assert len(Path(payload["work_dir"]).name) == 32
        assert patch["clean_picture_path"] == patch["exports"]["clean_picture"]
        assert patch["timeline"] == {
            "width": 720,
            "height": 1280,
            "duration_s": 15.0,
            "overlays": [{"kind": "ai_label", "text": "AI生成"}],
        }
    assert first["deliverable"] != second["deliverable"]
    assert previous.read_bytes() == b"previous approved bytes"
    assert context.font_calls == [True, True]


def test_compose_rejects_old_packaging_before_starting_a_render(context, monkeypatch):
    calls = compose_node(context, monkeypatch)
    context.state["outro_s"] = 4.0
    with pytest.raises(GateError, match="重新生成包装") as caught:
        run_node(context, "n15_compose")
    assert caught.value.status == 409
    assert calls == []


def test_compose_retains_visual_review_gate_before_clock_or_render(context, monkeypatch):
    calls = compose_node(context, monkeypatch)
    monkeypatch.setattr("workers.workflow.film.needs_human_review", lambda *_: True)
    with pytest.raises(GateError, match="人工放行") as caught:
        run_node(context, "n15_compose")
    assert caught.value.status == 409
    assert calls == []
    assert context.clock_calls == []


def test_compose_cannot_drop_ai_label_after_forwarding_clock(context, monkeypatch):
    compose_node(context, monkeypatch, label=False)
    with pytest.raises(GateError, match="AI生成"):
        run_node(context, "n15_compose")
    assert context.font_calls == [True]


def test_compose_cannot_skip_font_gate(context, monkeypatch):
    compose_node(context, monkeypatch)

    def denied():
        raise GateError("font licence denied")

    monkeypatch.setattr(invoke, "enforce_fonts", denied)
    with pytest.raises(GateError, match="font licence denied"):
        run_node(context, "n15_compose")
