import threading
import time

import pytest
from pydantic import ValidationError

from gateway.constants import NO_RENDERED_TEXT
from gateway.router import RouteTable, default_routes_path
from workers.nodes.n08_keyframe.node import run
from workers.nodes.n08_keyframe.qa import QAError, check
from workers.nodes.n08_keyframe.tests.shots import request, shot
from workers.schemas.asset import Candidate
from workers.schemas.script import GenerationMode


def test_each_shot_gets_four_keyframes_and_hides_on_screen_text(gateway) -> None:
    person = shot(
        shot_id="S02",
        order=2,
        purpose="人物出镜",
        visual="已授权人物的中景。画面无任何文字、无 Logo、无价格、无电话号码。",
        subject_refs=["person:老板"],
        scene_ref="scene:interview_01",
        generation_mode="reference_to_video",
        on_screen_text=[],
        voiceover="The owner speaks.",
    )
    result = run(request(shot(), person), gateway=gateway)
    rows = check(result)
    by_shot: dict[str, list[Candidate]] = {}
    for row in rows:
        by_shot.setdefault(row.shot_id, []).append(row)
    product = [row for row in by_shot["S01"] if row.params["frame"] == "first"]
    assert len(product) == 4
    assert len({row.params["seed"] for row in product}) == 4
    assert sum(row.selected for row in product) == 1
    assert all(NO_RENDERED_TEXT in row.params["prompt"] for row in product)
    assert all("30 MPa" not in row.params["prompt"] for row in product)
    assert all(row.params["prompt"].startswith("Photographic still") for row in product)
    assert all("stand-in" in row.params["prompt"] for row in product)
    assert all(row.model and row.uri for row in product)
    person_rows = by_shot["S02"]
    assert person_rows[0].params["prompt"].startswith("Subject-first frame")
    assert person_rows[0].params["shot_type"] == "person"
    again = run(request(shot(), person), gateway=gateway)
    assert again.payload["candidates"] == result.payload["candidates"]


def test_push_in_also_renders_a_matching_end_frame(gateway) -> None:
    result = run(
        request(shot(camera="slow_push_in", generation_mode="image_to_video")),
        gateway=gateway,
    )
    rows = check(result)
    first = [row for row in rows if row.params["frame"] == "first"]
    last = [row for row in rows if row.params["frame"] == "last"]
    assert len(first) == 4 and len(last) == 4
    chosen_first = next(row for row in first if row.selected)
    chosen_last = next(row for row in last if row.selected)
    assert chosen_first.params["seed"] == chosen_last.params["seed"]
    assert "opening frame" in chosen_last.params["prompt"]


def test_first_last_mode_renders_an_end_frame_for_a_locked_camera(gateway) -> None:
    result = run(
        request(shot(generation_mode=GenerationMode.first_last_frame.value)),
        gateway=gateway,
    )
    rows = check(result)
    assert any(row.params["frame"] == "last" for row in rows)


def test_motion_graphics_are_not_sent_to_the_image_model(gateway) -> None:
    graphic = shot(
        shot_id="S02",
        order=2,
        purpose="参数",
        camera="locked_off",
        shot_size="medium",
        subject_refs=[],
        scene_ref="scene:graphic_01",
        generation_mode="motion_graphics",
        visual="干净的图形底。画面无任何文字、无 Logo、无价格、无电话号码。",
        on_screen_text=[{"text": "30 MPa", "style": "spec_badge", "in": 0.2, "out": 3.0}],
    )
    result = run(request(shot(), graphic), gateway=gateway)
    check(result)
    assert result.payload["skipped"] == ["S02"]
    assert all(row["shot_id"] != "S02" for row in result.payload["candidates"])
    logs = [
        row
        for row in gateway.store.list_logs(project_id="proj-1")
        if row["shot_id"] == "S02" and row["task"] == "image"
    ]
    assert logs == []


def test_one_shot_failing_does_not_block_the_other(gateway) -> None:
    class Guard:
        def __init__(self, inner) -> None:
            self.inner = inner

        def generate_image(self, prompt, **kwargs):
            if kwargs.get("shot_id") == "S02":
                raise RuntimeError("bad shot")
            return self.inner.generate_image(prompt, **kwargs)

        def __getattr__(self, name):
            return getattr(self.inner, name)

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
    with pytest.raises(QAError):
        run(request(shot(), other), gateway=Guard(gateway), max_attempts=1)
    finished = [
        row["shot_id"]
        for row in gateway.store.list_logs(project_id="proj-1")
        if row["task"] == "image" and row["status"] == "ok"
    ]
    assert "S01" in finished
    assert "S02" not in finished


def test_shots_are_generated_in_parallel() -> None:
    class Slow:
        def __init__(self) -> None:
            self.routes = RouteTable(default_routes_path())
            self.inflight = 0
            self.peak = 0
            self.lock = threading.Lock()

        def generate_image(self, prompt, **kwargs):
            with self.lock:
                self.inflight += 1
                self.peak = max(self.peak, self.inflight)
            try:
                time.sleep(0.05)
            finally:
                with self.lock:
                    self.inflight -= 1
            return {"uri": f"mock://image/{kwargs.get('shot_id')}-{kwargs.get('seed')}"}

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
    result = run(request(shot(), other, keyframe_candidates=3), gateway=gateway)
    check(result)
    assert gateway.peak >= 2


def test_invalid_input_and_timeout(gateway) -> None:
    with pytest.raises(ValidationError):
        run({"project_id": "proj-1", "payload": {}}, gateway=gateway)
    with pytest.raises(ValidationError):
        run(request(shot(), keyframe_candidates=2), gateway=gateway)
    with pytest.raises(TimeoutError):
        run(request(shot()), gateway=gateway, timeout_s=0)
    with pytest.raises(ValueError):
        run(
            {"project_id": "proj-1", "shot_id": "missing", "payload": request(shot())["payload"]},
            gateway=gateway,
        )


def test_single_shot_rerun(gateway) -> None:
    raw = request(shot(), shot(shot_id="S02", order=2, on_screen_text=[]))
    full = run(raw, gateway=gateway)
    check(full)
    one = run({**raw, "shot_id": "S02"}, gateway=gateway)
    rows = check(one)
    assert {row.shot_id for row in rows} == {"S02"}
