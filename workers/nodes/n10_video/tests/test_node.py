import threading
import time

import pytest
from pydantic import ValidationError

from gateway.constants import NO_RENDERED_TEXT
from gateway.router import RouteTable, default_routes_path
from workers.media.trim import probe_duration_s
from workers.nodes.n08_keyframe.node import run as run_keyframes
from workers.nodes.n08_keyframe.tests.shots import request, shot
from workers.nodes.n10_video.node import run
from workers.nodes.n10_video.prompts import render_video
from workers.nodes.n10_video.qa import check


def test_video_templates_forbid_text_and_differ() -> None:
    shared = {
        "camera": "The camera eases forward.",
        "subject": "An unmarked pump.",
        "scene": "Workshop.",
        "style": "Cool light.",
        "motion": "low",
        "negative": NO_RENDERED_TEXT,
        "closing": False,
    }
    seedance = render_video(model="doubao-seedance-1-0-pro-250528", **shared)
    kling = render_video(model="kling-o3", **shared)
    wan = render_video(model="wanx-v1", **shared)
    assert seedance != kling != wan
    assert seedance.startswith("Opening-frame move")
    assert kling.startswith("Subject-led move")
    assert wan.startswith("Atmosphere plate")
    for text in (seedance, kling, wan):
        assert NO_RENDERED_TEXT in text


def test_routes_follow_shot_family() -> None:
    table = RouteTable(default_routes_path())
    assert table.resolve("video", "product", "zh").id == "video-product"
    assert table.resolve("video", "person", None).id == "video-person"
    assert table.resolve("video", "person", None).primary.model == "kling-o3"
    assert table.resolve("video", "multi_ref", None).id == "video-multi-ref"
    assert table.resolve("video", "atmosphere", None).primary.model == "wanx-v1"
    assert table.resolve("video", None, None).id == "video-default"
    assert table.resolve("image", "person", None).id == "image-person"
    assert table.resolve("image", "product", None).id == "image-default"


def test_mock_video_honors_requested_duration(gateway) -> None:
    out = gateway.generate_video("pump turns slowly", seed=1, duration_s=5, shot_type="product")
    assert out["duration_s"] == 5
    measured = probe_duration_s(gateway.registry["mock"].store.get(out["uri"]))
    assert abs(measured - 5) < 0.2


def test_product_clip_is_trimmed_with_margins(gateway) -> None:
    frames = run_keyframes(request(shot()), gateway=gateway)
    result = run(
        {
            "project_id": "proj-1",
            "payload": {
                "script": frames.payload["script"],
                "candidates": frames.payload["candidates"],
                "video_candidates": 4,
            },
        },
        gateway=gateway,
    )
    rows = check(result)
    assert len(rows) == 4
    assert sum(row.selected for row in rows) == 1
    assert len({row.params["seed"] for row in rows}) == 4
    for row in rows:
        assert row.params["duration"] == 5
        assert row.params["motion_strength"] == "low"
        assert row.params["shot_type"] == "product"
        assert row.params["trimmed"] is True
        assert row.params["head_margin_s"] > 0
        assert row.params["tail_margin_s"] > 0
        assert NO_RENDERED_TEXT in row.params["prompt"]
        assert "30 MPa" not in row.params["prompt"]
        assert row.params["prompt"].startswith("Opening-frame move")
        measured = probe_duration_s(gateway.media_store.get(row.uri))
        assert abs(measured - 4.0) < 0.25
    logs = [
        row
        for row in gateway.store.list_logs(project_id="proj-1")
        if row["task"] == "video" and row["status"] == "ok"
    ]
    assert logs
    assert {row["params"]["route_id"] for row in logs} == {"video-product"}
    assert logs[0]["params"]["shot_type"] == "product"


def test_atmosphere_uses_the_wan_template_and_a_longer_interval() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.routes = RouteTable(default_routes_path())
            self.prompts: list[str] = []
            self.durations: list[float] = []
            self.types: list[str] = []

        def generate_video(self, prompt, duration_s=None, **kwargs):
            self.prompts.append(prompt)
            self.durations.append(duration_s)
            self.types.append(kwargs.get("shot_type"))
            return {"uri": f"mock://video/{kwargs.get('seed')}", "duration_s": duration_s}

    opening = _opening("S01")
    atmosphere = shot(
        purpose="钩子",
        camera="slow_push_in",
        shot_size="medium",
        subject_refs=[],
        scene_ref="scene:opening_01",
        generation_mode="text_to_video",
        visual="开场环境。画面无任何文字、无 Logo、无价格、无电话号码。",
        on_screen_text=[],
        duration_s=4.8,
    )
    gateway = Recorder()
    result = run(
        {
            "project_id": "proj-1",
            "payload": {
                "script": request(atmosphere)["payload"]["script"],
                "candidates": [opening],
                "video_candidates": 3,
            },
        },
        gateway=gateway,
    )
    rows = check(result)
    assert len(rows) == 3
    assert gateway.types == ["atmosphere", "atmosphere", "atmosphere"]
    assert gateway.durations == [10, 10, 10]
    assert all(prompt.startswith("Atmosphere plate") for prompt in gateway.prompts)
    assert all(row.params["motion_strength"] == "medium" for row in rows)
    assert all(row.params["duration"] == 10 for row in rows)


def test_motion_graphics_skip_video() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.routes = RouteTable(default_routes_path())
            self.calls = 0

        def generate_video(self, prompt, duration_s=None, **kwargs):
            self.calls += 1
            return {"uri": "mock://video/x", "duration_s": duration_s}

    graphic = shot(
        purpose="参数",
        camera="locked_off",
        shot_size="medium",
        subject_refs=[],
        scene_ref="scene:graphic_01",
        generation_mode="motion_graphics",
        visual="干净的图形底。画面无任何文字、无 Logo、无价格、无电话号码。",
    )
    gateway = Recorder()
    result = run(
        {
            "project_id": "proj-1",
            "payload": {
                "script": request(graphic)["payload"]["script"],
                "candidates": [_opening("S01")],
            },
        },
        gateway=gateway,
    )
    check(result)
    assert result.payload["candidates"] == []
    assert result.payload["skipped"] == ["S01"]
    assert gateway.calls == 0


def test_one_video_failure_does_not_block_the_other() -> None:
    class Guard:
        def __init__(self) -> None:
            self.routes = RouteTable(default_routes_path())
            self.seen: list[str] = []

        def generate_video(self, prompt, duration_s=None, **kwargs):
            shot_id = kwargs.get("shot_id")
            self.seen.append(shot_id)
            if shot_id == "S02":
                raise RuntimeError("bad shot")
            return {"uri": f"mock://video/{shot_id}-{kwargs.get('seed')}", "duration_s": duration_s}

    other = shot(
        shot_id="S02",
        order=2,
        purpose="钩子",
        camera="locked_off",
        shot_size="wide",
        subject_refs=[],
        scene_ref="scene:opening_01",
        generation_mode="text_to_video",
        visual="开场环境。画面无任何文字、无 Logo、无价格、无电话号码。",
        on_screen_text=[],
    )
    gateway = Guard()
    result = run(
        {
            "project_id": "proj-1",
            "payload": {
                "script": request(shot(), other)["payload"]["script"],
                "candidates": [_opening("S01"), _opening("S02")],
                "video_candidates": 3,
            },
        },
        gateway=gateway,
        max_attempts=1,
    )
    check(result)
    assert result.payload["generation_failed"] == ["S02"]
    assert {row["shot_id"] for row in result.payload["candidates"]} == {"S01"}
    assert "S01" in gateway.seen
    assert "S02" in gateway.seen


def test_video_shots_overlap() -> None:
    class Slow:
        def __init__(self) -> None:
            self.routes = RouteTable(default_routes_path())
            self.inflight = 0
            self.peak = 0
            self.lock = threading.Lock()

        def generate_video(self, prompt, duration_s=None, **kwargs):
            with self.lock:
                self.inflight += 1
                self.peak = max(self.peak, self.inflight)
            try:
                time.sleep(0.05)
            finally:
                with self.lock:
                    self.inflight -= 1
            return {
                "uri": f"mock://video/{kwargs.get('shot_id')}-{kwargs.get('seed')}",
                "duration_s": duration_s,
            }

    other = shot(
        shot_id="S02",
        order=2,
        purpose="钩子",
        camera="locked_off",
        shot_size="wide",
        subject_refs=[],
        scene_ref="scene:opening_01",
        generation_mode="text_to_video",
        visual="开场环境。画面无任何文字、无 Logo、无价格、无电话号码。",
        on_screen_text=[],
    )
    gateway = Slow()
    result = run(
        {
            "project_id": "proj-1",
            "payload": {
                "script": request(shot(), other)["payload"]["script"],
                "candidates": [_opening("S01"), _opening("S02")],
                "video_candidates": 3,
            },
        },
        gateway=gateway,
    )
    check(result)
    assert gateway.peak >= 2


def test_invalid_input(gateway) -> None:
    with pytest.raises(ValidationError):
        run({"project_id": "proj-1", "payload": {}}, gateway=gateway)
    with pytest.raises(TimeoutError):
        run(
            {
                "project_id": "proj-1",
                "payload": {
                    "script": request(shot())["payload"]["script"],
                    "candidates": [_opening("S01")],
                },
            },
            gateway=gateway,
            timeout_s=0,
        )


def _opening(shot_id: str) -> dict:
    return {
        "candidate_id": f"kf-{shot_id}",
        "shot_id": shot_id,
        "node": "N8",
        "model": "mock-image",
        "params": {"seed": 1, "prompt": "still", "frame": "first"},
        "uri": f"mock://image/{shot_id}",
        "qa": {
            "scores": {
                "product_fidelity": 8,
                "motion_quality": 8,
                "aesthetics": 8,
                "prompt_match": 8,
                "artifact_free": 8,
            },
            "hard_fail": [],
            "total": 8.0,
            "evaluator": "rule-select-v0",
            "notes": "selected",
        },
        "selected": True,
    }
