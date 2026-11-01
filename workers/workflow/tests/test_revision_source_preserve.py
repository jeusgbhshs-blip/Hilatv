"""N18 reads original shot bytes; it never silently composes replacement color plates."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from workers.media.ffmpeg import encode_plate
from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
from workers.nodes.n15_compose.node import run as compose
from workers.nodes.runtime import placeholder_qa
from workers.schemas.asset import Candidate
from workers.schemas.script import Script
from workers.workflow import revise
from workers.workflow.store import (
    init_project,
    project_path,
    read_snapshot,
    save_node,
    update_snapshot,
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "160")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "120")
    project_id = "revision-pictures"
    init_project(project_id, status="completed", sentence="产品宣传")
    directory = project_path(project_id)
    return project_id, directory


def plate(directory: Path, name: str, rgb: tuple[int, int, int], frames=120) -> Path:
    path = directory / "original" / f"{name}.mp4"
    encode_plate(path, rgb=rgb, width=64, height=48, frames=frames, fps=30)
    return path


def pixel(path: str, at: float) -> tuple[int, int, int]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(at),
            "-i",
            path,
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    assert len(result.stdout) == 3
    return tuple(result.stdout)


def test_packaging_revision_reuses_actual_picture_and_keeps_original_bytes(project):
    project_id, directory = project
    original = plate(directory, "red", (220, 20, 20))
    original_bytes = original.read_bytes()
    board = storyboard(shot(duration_s=4, voiceover=""))
    board["shots"][0]["on_screen_text"] = [
        {"text": "¥99", "style": "spec_badge", "in": 0.2, "out": 3}
    ]
    clips = [
        {
            "shot_id": "S01",
            "path": str(original),
            "cards": [{"text": "¥99", "start_s": 0.2, "end_s": 3, "y_ratio": 0.6}],
        }
    ]
    elements, _, _ = revise._package(
        directory,
        project_id,
        Script.model_validate(board),
        None,
        None,
        160,
        120,
        brand_logo=True,
        clock={"target_duration_s": 5, "intro_s": 0, "outro_s": 1},
    )
    before = compose(
        {
            "project_id": project_id,
            "payload": {
                "script": board,
                "shot_clips": clips,
                "elements": elements,
                "intro_s": 0,
                "outro_s": 1,
                "target_duration_s": 5,
                "width": 160,
                "height": 120,
                "work_dir": str(directory / "before"),
            },
        },
        max_attempts=1,
    ).payload
    brief = json.loads(
        (Path(__file__).parents[2] / "schemas/tests/fixtures/brief.json").read_text()
    )
    brief.update(
        duration_s=5,
        aspect_ratios=["4:3"],
        languages=["zh"],
        generation_settings={"aspect_ratio": "4:3", "duration_s": 5},
    )
    save_node(project_id, "n01_brief", {"brief": brief})
    save_node(project_id, "n05_storyboard", {"script": board})
    save_node(project_id, "n14_packaging", {"elements": elements, "intro_s": 0, "outro_s": 1})
    save_node(project_id, "shot_director", {"shot_clips": clips})
    save_node(
        project_id,
        "n15_compose",
        {
            "script": board,
            "rendered_script": before["script"],
            "deliverable": before["exports"]["master"],
            "exports": before["exports"],
            "timeline": before["timeline"],
            "clean_picture_path": before["exports"]["clean_picture"],
        },
    )
    update_snapshot(
        project_id,
        deliverable=before["exports"]["master"],
        generation_settings={"aspect_ratio": "4:3", "duration_s": 5},
    )
    previous_master = Path(before["exports"]["master"]).read_bytes()

    class Gateway:
        def generate_text(self, *_args, **_kwargs):
            return {
                "targets": ["S01"],
                "change": {"price": "remove"},
                "keep": ["narration", "composition"],
            }

        def generate_video(self, *_args, **_kwargs):
            raise AssertionError("a packaging-only edit must not regenerate a video")

    result = revise.revise_project(project_id, "去掉价格", gateway=Gateway())
    assert result["video_shots"] == [] and result["status"] == "completed"
    assert original.read_bytes() == original_bytes
    assert Path(before["exports"]["master"]).read_bytes() == previous_master
    saved = json.loads((directory / "nodes/n15_compose.json").read_text())
    assert saved["production_clock"] == {"target_duration_s": 5, "intro_s": 0, "outro_s": 1}
    assert saved["rendered_script"]["shots"][0]["duration_s"] == 4
    assert saved["shot_clips"][0]["cards"] == []
    assert all(row.get("text") != "¥99" for row in saved["timeline"]["overlays"])
    red, green, blue = pixel(saved["clean_picture_path"], 0.5)
    assert red > green * 2 and red > blue * 2
    assert read_snapshot(project_id)["quality_pass"] is False


def test_fresh_target_and_unchanged_shot_use_distinct_real_sources(project):
    project_id, directory = project
    red = plate(directory, "red", (220, 20, 20), frames=69)
    blue = plate(directory, "blue", (20, 20, 220), frames=69)
    green = plate(directory, "fresh-green", (20, 220, 20), frames=69)
    originals = {path: path.read_bytes() for path in (red, blue)}
    board = storyboard(
        shot(duration_s=2.3, voiceover=""),
        shot(shot_id="S02", order=2, duration_s=2.3, voiceover=""),
    )
    state = {
        "timeline": {"clips": [{"clip_id": "S01", "path": str(red), "placeholder": True}]},
        "shot_clips": [
            {"shot_id": "S01", "path": str(blue)},
            {"shot_id": "S02", "path": str(blue)},
        ],
        "videos": [
            Candidate(
                candidate_id="fresh-video",
                shot_id="S02",
                node="N10",
                model="mock-video",
                uri="mock://fresh",
                params={"mock": True},
                qa=placeholder_qa(selected=False),
                selected=True,
            ).model_dump(mode="json")
        ],
    }
    rendered = {}
    elements, _, _ = revise._package(
        directory,
        project_id,
        Script.model_validate(board),
        None,
        None,
        160,
        120,
        brand_logo=True,
        clock={"target_duration_s": 7, "intro_s": 0, "outro_s": 2.4},
    )
    revise._compose(
        directory,
        project_id,
        Script.model_validate(board),
        [],
        [],
        elements,
        None,
        None,
        0,
        2.4,
        160,
        120,
        clock={"target_duration_s": 7, "intro_s": 0, "outro_s": 2.4},
        source_state=state,
        fresh={"S02": green.read_bytes()},
        render_result=rendered,
    )
    assert rendered["shot_clips"][0]["path"] == str(red)
    fresh_path = Path(rendered["shot_clips"][1]["path"])
    assert fresh_path != blue and fresh_path.read_bytes() == green.read_bytes()
    assert all(path.read_bytes() == data for path, data in originals.items())
    assert all(
        row["placeholder"] is True
        for row in rendered["timeline"]["clips"]
        if row["clip_id"] in {"S01", "S02"}
    )
    assert rendered["placeholder_shots"] == ["S01", "S02"]
    assert json.loads(Path(rendered["timeline_path"]).read_text()) == rendered["timeline"]
    first = pixel(rendered["exports"]["clean_picture"], 0.5)
    second = pixel(rendered["exports"]["clean_picture"], 3)
    assert first[0] > first[1] * 2 and first[0] > first[2] * 2
    assert second[1] > second[0] * 2 and second[1] > second[2] * 2


@pytest.mark.parametrize("bad", ["missing", "broken", "outside", "burned", "clean_full"])
def test_missing_or_untrusted_old_source_fails_without_touching_previous_master(
    project, tmp_path, bad
):
    project_id, directory = project
    previous = directory / "playback/master.mp4"
    previous.parent.mkdir()
    previous.write_bytes(b"previous master must remain byte-identical")
    source = directory / "old.mp4"
    state = {"deliverable": str(previous)}
    if bad == "broken":
        source.write_bytes(b"not video or an image")
    elif bad == "outside":
        source = tmp_path / "other-project.mp4"
        source.write_bytes(b"private")
    elif bad == "burned":
        source = previous
    elif bad == "clean_full":
        source = previous
        state["clean_picture_path"] = str(source)
    state["shot_clips"] = [{"shot_id": "S01", "path": str(source)}]
    board = storyboard(shot(duration_s=4, voiceover=""))
    project_before = (directory / "project.json").read_bytes()
    with pytest.raises(revise.RevisionError, match="S01.*上一版已保留"):
        revise._compose(
            directory,
            project_id,
            Script.model_validate(board),
            [],
            [],
            [],
            None,
            None,
            0,
            1,
            64,
            48,
            source_state=state,
        )
    assert previous.read_bytes() == b"previous master must remain byte-identical"
    assert (directory / "project.json").read_bytes() == project_before
    assert not (directory / "nodes").exists()


def test_revision_starts_from_rendered_cuts_and_updates_saved_alignment():
    original = storyboard(shot(duration_s=3, voiceover=""))
    rendered = copy.deepcopy(original)
    rendered["shots"][0]["duration_s"] = 4
    script = revise._script({"script": original, "rendered_script": rendered})
    assert script.shots[0].duration_s == 4
    patches = {
        "n12_music": {"aligned_script": original},
        "n15_compose": {"exports": {"clean_picture": "old-clean.mp4"}},
    }
    revise._remember(
        patches,
        script=script,
        brand=None,
        voiceovers=[],
        keyframes=[],
        videos=[],
        cues=[],
        elements=[],
        intro_s=0,
        outro_s=1,
        deliverable="new-master.mp4",
    )
    assert patches["n12_music"]["aligned_script"] == rendered
    assert patches["n15_compose"]["exports"]["clean_picture"] == "old-clean.mp4"


def test_legacy_revision_uses_aligned_cuts_when_rendered_script_was_not_saved():
    original = storyboard(shot(duration_s=3, voiceover=""))
    aligned = copy.deepcopy(original)
    aligned["shots"][0]["duration_s"] = 4
    state = {"script": original, "aligned_script": aligned}
    assert revise._script(state).shots[0].duration_s == 4
    rendered = copy.deepcopy(aligned)
    rendered["shots"][0]["duration_s"] = 5
    state["rendered_script"] = rendered
    assert revise._script(state).shots[0].duration_s == 5


def test_legacy_per_shot_image_is_recovered_without_touching_its_bytes(project):
    _project_id, directory = project
    image = directory / "media/S01.bin"
    image.parent.mkdir()
    Image.new("RGB", (64, 48), (200, 20, 20)).save(image, format="PNG")
    before = image.read_bytes()
    board = storyboard(shot(duration_s=4, voiceover=""))
    clips = revise._revision_clips(directory, board, {}, {})
    assert clips[0]["path"] == str(image)
    assert image.read_bytes() == before


def test_unreadable_fresh_output_never_silently_falls_back_to_old_picture(project):
    _project_id, directory = project
    original = plate(directory, "red", (220, 20, 20))
    before = original.read_bytes()
    state = {"shot_clips": [{"shot_id": "S01", "path": str(original)}]}
    board = storyboard(shot(duration_s=4, voiceover=""))
    with pytest.raises(revise.RevisionError, match="S01.*上一版已保留"):
        revise._revision_clips(directory, board, state, {"S01": b"bad provider bytes"})
    assert original.read_bytes() == before
